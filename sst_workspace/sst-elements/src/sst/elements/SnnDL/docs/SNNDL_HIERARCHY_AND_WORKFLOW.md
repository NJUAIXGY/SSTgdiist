# SnnDL 层次结构与工作流（以 4×4 Mesh 模板为例）

本文件是 **SnnDL 的“总览型”文档**：用清晰的层次结构（Hierarchy）解释 **每一层做什么、通过什么接口交互、以及完整的端到端数据流**。  
它不取代各子目录 `README.md`（每个目录的细节仍以各自 README 为准），而是提供“一眼看懂 SnnDL 怎么跑起来”的主线视角。

> 约束：本文以 **SNN 范畴内的多 compute core / 多 neuron model** 为目标，不改变 GAS/Spike/Synapse 语义，不改变脚本参数口径；并以 `sst_dram_si/test_mesh_4x4.py` 模板作为使用示例。

---

## 0. 快速入口（先跑起来）

### 0.1 构建与安装（修改生效必须 install）

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4
make install
```

### 0.2 运行 4×4 mesh 模板（10us/100us）

> 模板手册：`sst_dram_si/docs/mesh_template_guide_20251122-000250.md`

```bash
cd "sst_dram_si"
export "MESH_SIM_TIME=10us"
./tools/run_mesh_with_time.sh

export "MESH_SIM_TIME=100us"
./tools/run_mesh_with_time.sh
```

输出目录：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/YYYYMMDD-HHMMSS/`  
关键回归摘要：`essential_summary_mesh.json`

---

## 1. Hierarchy（层次结构）与职责边界

### 1.1 目录层级（结构视角）

```
SnnDL/
├── api/            # 跨层稳定接口（窄抽象：IMemoryAccess/INocTransport/ISnnComputeCore...）
├── events/         # 事件与 payload（SpikeEvent/NocPacketEvent/GatingDecision...）
├── components/     # SST 可加载组件装配壳（ELI 注册对象：MultiCorePE/GatherBufferIF/SnnNIC...）
├── control/        # CoreShell（平台壳：time/packet/stat；不含业务状态机）
├── compute/        # 可替换 compute core（动力学/学习/模型；不触碰 StandardMem/NoC）
├── services/       # 事务子系统（memory/noc/synapse/stimulus/legacy）
│   └── workload/   # Workload 插件（snn/stream/...）：业务主链路闭环
├── docs/           # 设计/路线图/阶段性方案（包含本文）
└── tests/          # include/边界自检
```

### 1.2 依赖方向（边界视角）

> 目标：上层“装配/调度”依赖下层“接口/子系统”，避免反向依赖导致耦合膨胀。

```
components/* (装配壳：端口/clock/stat/后端句柄)
  └─ control/* (CoreShell：time/packet/stat)
      └─ services/workload/* (业务主链路：snn/stream/...)
          ├─ compute/* (可替换动力学：ISnnComputeCore；仅 snn 使用)
          ├─ services/synapse/* (突触语义：weights/route/gas；仅 snn 使用)
          ├─ services/stimulus/* (刺激：Step/外部输入；仅 snn 使用)
          ├─ services/noc/* (传输：NocPacketEvent；平台面)
          └─ services/memory/* (纯内存：addr→bytes；平台面)
api/* (窄接口)  ← 以上所有层均可依赖
events/* (payload) ← components/services/control 传递数据时使用
```

### 1.3 “每一层到底负责什么”（职责视角）

- **components/**：SST 组件装配壳（端口/Link/Clock/init/setup/finish/stat），尽量不写算法事务。
- **control/**：CoreShell（平台壳：时钟驱动、packet 递送、统计汇聚）；不包含业务状态机。
- **compute/**：动力学与发放判定（可替换 compute core；可替换 neuron model）；不直接依赖 StandardMem/NoC。
- **services/memory/**：纯 `addr+size ↔ bytes`（pending/回包分发/断言式诊断）；不出现 weight/synapse/bcsr/route 语义。
- **services/synapse/**：突触语义闭环（weights/BCSR/缓存/ΔV + route/fanout/gating + GAS 辅助结构）。
- **services/noc/**：纯传输（send/recv/forward/本地投递 + ring tick）；payload 为 `NocPacketEvent`，不解析 Spike 语义。
- **services/stimulus/**：刺激域（何时注入/注入哪些源）；通过 NoC/Route 完成投递与外发。
- **services/workload/**：业务主链路（snn/stream/...）；负责把 compute/synapse/stimulus 组合成可运行闭环。

---

## 2. 核心接口（API）与“谁实现/谁调用”

下面列的是“跨层稳定接口”的主干（更细节见 `api/README.md`）：

### 2.1 Compute（计算层）
- **接口**：`compute/ISnnComputeCore.h`
- **实现**：`compute/DefaultSnnComputeCore`（`compute/SnnComputeCore.{h,cc}`）
- **调用者**：`services/workload/snn/SnnWorkload`（在收敛点调用 `endCycle()`，并用 `drainOutputs()` 拉取输出）

关键交互点（约定）：
- 输入：`onSpikeDelivered(SpikeEvent*)`、`applySynapticDelta(post_local, dv)`
- 收敛：`endCycle(now_cycle)` / `endCycleCandidates(now_cycle, candidates)`
- 输出：`drainOutputs(std::vector<FireEvent>&)`

### 2.2 Memory（纯内存层）
- **接口**：`api/IMemoryAccess.h`
- **实现**：`services/memory/StandardMemAccess.{h,cc}`
- **调用者**：`services/synapse/weights/WeightMemorySubsystem`（通过 `IMemoryAccess` 请求 bytes）

关键约束：
- Memory 只保证“正确 bytes”，不解释 float/idx/rowptr；
- 回包 `resp_bytes < req_bytes` 直接 fail-fast（断言式诊断，避免静默腐坏）。

### 2.3 Weights（权重语义层）
- **接口**：`api/SnnWeightReader.h`（`IWeightReader`）
- **实现**：`services/synapse/weights/WeightMemorySubsystem.{h,cc}`
- **调用者**：compute core（通过 `ComputeCoreContext.weight_reader` 注入）

### 2.4 Route（fanout/通信事务层）
- **接口**：`api/ISynapseRoute.h`（路由构建/查询）
- **实现**：`services/synapse/route/SynapseRouteSubsystem.{h,cc}`
- **调用者**：`services/synapse/route/SpikeCommSubsystem`（fanout + 构造 SpikeEvent）

### 2.5 NoC（传输层）
- **接口**：`api/INocTransport.h`
- **实现**：`services/noc/NocSubsystem.{h,cc}`
- **调用者**：
  - `api/NocSpikeTransport.h`（把 Spike 发送映射为 NoC packet 发送）
  - `services/synapse/route/SpikePacketBridge`（编码/解码并调用 NoC）

---

## 3. 工作流（以 4×4 Mesh 模板为例）

> 模板入口：`sst_dram_si/test_mesh_4x4.py`  
> 驱动脚本：`sst_dram_si/tools/run_mesh_with_time.sh`（会设置 `MESH_RUN_DIR` 并生成 `essential_summary_mesh.json`）

### 3.1 运行时装配：Python 模板做了什么

1) **统计输出**（必须在创建组件前设置）  
`test_mesh_4x4.py` 会提前配置 `sst.setStatisticOutput("sst.statOutputCSV")`，并把 `mesh_stats.csv` 写到 `MESH_RUN_DIR`。

2) **读取 `local_run_config.json`**（可选覆盖）  
模板会从 `sst_dram_si/local_run_config.json` 读取一批开关，例如：
- `step_random_activation_enable / step_activation_fraction / step_activation_fanout / step_activation_seed`
- `global_step_sync_enable`
- `use_soa / use_aosoa / aosoa_block_rows`
- `routing_mode / synapse_format / force_dense / bcsr_auto_detect`

3) **创建网络与 PE 网格**  
模板会按 `MESH_SIZE×MESH_SIZE` 创建多个 `SnnDL.MultiCorePE`，并装配：
- 每个 PE 多个 core（`SnnDL.SnnPESubComponent`，即 control 壳）
- 内存前端（`SnnDL.GatherBufferIF`，StandardMem 子组件）
- NIC（`SnnDL.SnnNIC`，对接 merlin/simpleNetwork）
- 路由器（`merlin.hr_router`）与链路（north/south/east/west）

> 这一步是“系统装配”，其细节属于 `components/**` 的职责范围。

### 3.2 时序主线：GAS 窗口（Gather/Apply/Scatter）

以下描述的是“单个 core（SnnPESubComponent）在一个窗口里如何推进”的主线：

1) **Gather（收集边/触达集合）**
- 输入 spike 到达后，control 会决定是否记录 edge（门控/阶段门控/容量门控），并把 edge 交给 synapse 侧的边集合/权重编排。

2) **Apply（发起窗口读，得到权重并累加 ΔV）**
- `WeightMemorySubsystem` 基于 edge 集合与 budget/outstanding 规则发起读：
  - 通过 `IMemoryAccess` 发起 `read(addr, bytes)`；
  - 收到 bytes 后在 weights 层解析为 float 权重；
  - 调用 `accUpdate(post_local, dv)` 把 ΔV 写入累加器（`services/synapse/gas/AccumulatorOps`）。

3) **Scatter（把 ΔV 应用到 compute，并产生 fire events）**
- control 从累加器收集 `(post, dv)` 对：
  - 逐条 `compute_core_->applySynapticDelta(post, dv)`；
  - 在“统一收敛点”调用 `compute_core_->endCycle(now_cycle)`；
  - 然后 `compute_core_->drainOutputs(fired)` 拉取输出 fire events。

### 3.3 输出主线：fire → fanout → NoC

1) **fanout/构造 SpikeEvent**  
`SpikeCommSubsystem` 对每个 fire event：
- 调 `ISynapseRoute::computeFanout()` 得到目的集合；
- 构造 `events/SpikeEvent`（源 neuron、目的 neuron、目的 node、权重/时间戳等）；

2) **编码为 NoC packet 并发送**  
`SpikeCommSubsystem` 通过 `ISpikeTransport` 发出（常见实现为 packet transport）：
- `SpikePacketBridge` 将 `SpikeEvent` 编码为 `NocPacketEvent`；
- `INocTransport::sendFromCore(src_core, pkt)` 交给 `NocSubsystem`；
- `NocSubsystem` 决定本地投递还是外发（NIC/mesh）。

3) **接收与投递**  
- NIC/链路收到 `NocPacketEvent` 后交给 `NocSubsystem` 入队；
- `MultiCorePE` 每拍调用 `drainIncomingQueue()`，触发 `deliver_to_endpoint(dst_core, pkt)`；
- `SpikePacketBridge` 解码回 `SpikeEvent` 并递送到目标 core（control 收到后进入下一轮 Gather/Apply/Scatter）。

---

## 4. 使用展示：如何改参数、看输出、做回归

### 4.1 推荐的“最小回归”节奏

- 先跑 `10us`：不崩溃 + `gas.windows` 数量级合理（10us 允许 `neurons_fired_total=0`）
- 再跑 `100us`：`neurons_fired_total` 与 `gas.*_p95` 不应异常归零，用于稳定性回归
- 同配置重复跑一次 `100us`：允许轻微漂移（建议用 `sst_dram_si/tools/compare_essential_summary_mesh.py` 做容忍度对比）

### 4.2 输出文件怎么看

模板输出目录（run_dir）包含：
- `mesh_run.log`：完整运行日志
- `mesh_stats.csv`：SST CSV 统计（用于聚合到 `essential_summary_mesh.json`）
- `pe*/pe_stage_events_db.csv`：阶段事件（用于 windows 计数与 p95）
- `pe*/coreXX_window_metrics.csv`：窗口统计（payload/bursts/inflight_peak 等）
- `essential_summary_mesh.json`：汇总摘要（建议作为回归判定主入口）

### 4.3 最常用的开关（建议从模板手册查）

优先以 `sst_dram_si/docs/mesh_template_guide_20251122-000250.md` 为准；这里仅列“最常用的一层”：
- `MESH_SIM_TIME`：仿真时长
- `local_run_config.json`：
  - `step_random_activation_enable / step_activation_fraction / step_activation_fanout / step_activation_seed`
  - `global_step_sync_enable`
  - `window_read_debug / debug_target_pe / debug_target_core / window_read_debug_all_cores`
  - `synapse_format / bcsr_auto_detect / force_dense`

---

## 5. 扩展点（SNN 内：多 compute core / 多模型）

### 5.1 新增 compute core（保持 GAS/Spike/Synapse 语义不变）

1) 在 `compute/` 新增实现类：`class XxxComputeCore : public ISnnComputeCore`
2) 在 `compute/createComputeCoreByName()` 注册名称（例如 `compute_core_impl=xxx`）
3) 在模板/脚本里设置 `compute_core_impl=xxx`
4) 必跑回归：`10us → 100us → 100us(重复)`（SNN 允许轻微漂移时建议用 `sst_dram_si/tools/compare_essential_summary_mesh.py` 做容忍度对比）

### 5.2 新增 neuron model

现有模型选择由 `compute/SnnNeuronModel.h` 提供（LIF/Izhikevich/AdEx）。  
新增模型的推荐方式是：在 `SnnNeuronModel.h` 增加一个新 `NeuronModelType` 与 `createNeuronModel()` 分支，并保持默认参数有合理兜底。

---

## 6. 进一步阅读（按主题）

- 全局路线图：`docs/SUBSYSTEM_MODULARIZATION_ROADMAP.md`
- 通用控制壳设计：`docs/UNIVERSAL_CONTROL_CORE_DESIGN.md`
- 完成态 DoD：`docs/plans/2026-01-03-universal-core-completion.md`
