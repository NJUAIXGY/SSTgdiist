# SnnDL 子系统化终局路线图（Memory / Synapse+Route / Stimulus / NoC / NeuralCompute）

> 主人目标（最终态）：**MultiCorePE 变“纯控制壳”**，SNN 事务全部下沉到子系统；  
> 路由归入 **Synapse/Route**（而不是 NoC）；Stimulus（Step 注入/外部刺激）独立成域并依赖 Synapse/Route + NoC；  
> 内存子系统 **彻底不出现“权重/突触”语义**，只提供“地址→字节块”的访问能力喵 (..•˘_˘•..)

本路线图在 `docs/UNIVERSAL_CONTROL_CORE_DESIGN.md` 的基础上进一步“收紧边界”，用于指导后续多阶段重构推进。  
推进原则：**每一步都必须能跑通 `MESH_SIM_TIME=100us` 回归**，并保持关键统计口径稳定（允许极小浮动，但禁止出现 `neurons_fired_total=0` 的非确定性回归）。

---

## 0. 范围、约束与验收口径

### 0.0 Phase1 详细实施计划（Task-by-task）

- “完成态”DoD 与执行清单：`docs/plans/2026-01-03-universal-core-completion.md`

### 0.1 范围（In-scope）
- 代码范围：`sst_workspace/sst-elements/src/sst/elements/SnnDL/**`
- 目标拆分：
  - **Memory**：纯地址/字节读写 + pending/回包分发 +（可选）聚合/缓存前端（但不含权重语义）
  - **Synapse/Route**：权重/BCSR 语义、窗口边集合、ΔV 累加、路由构建与 fanout 查询（不负责注入时基）
  - **Stimulus**：Step 注入/外部刺激；选源 +（可选）调用路由 fanout 生成 spikes；通过 NoC 投递/外发
  - **NoC**：send/recv/forward（消息传输与本地转发），不做 fanout 选择，不解析权重
  - **NeuralCompute**：神经动力学与发放判定（已由 `compute/ISnnComputeCore` 实现）
- **MultiCorePE**：只负责装配/调度/统计汇聚/端口连接；不包含“step 选源、BCSR 解析、fanout 选择、ΔV 计算”等 SNN 事务逻辑。

### 0.2 非目标（Out-of-scope）
- 不引入新的 compute core 范式（先把边界切干净）
- 不改变 Python 脚本参数名与关键行为语义（兼容优先）
- 不在一次提交中“大手术搬家”：必须可增量回归

### 0.3 回归基线（强制 100us）
- 运行命令（与模板一致）：
  - `cd sst_dram_si && export MESH_SIM_TIME=100us && ./tools/run_mesh_with_time.sh`
- 建议固定对比字段（来自 `essential_summary_mesh.json`）：
  - `spike_activity.neurons_fired_total`（禁止为 0；建议连续 3 次 run 完全一致）
  - `step_activation.spikes_injected_total / invocations`
  - `memory.memory_requests / memory.memory_bytes`
  - `nic.packets_sent / packets_recv`
  - `window_metrics.payload_bytes_avg / bursts_avg / inflight_peak_max`
- “确定性”验收：同配置连续跑 3 次，以上字段应完全一致（首选）或在可解释的小范围内一致；建议使用 `sst_dram_si/tools/compare_essential_summary_mesh.py` 做容忍度对比。

### 0.4 回归执行清单（建议每个 Phase 都照此打勾）

> 目标：让“每一步都跑 100us”变成机械流程，减少漏项。

1) 构建安装（SnnDL 生效必须 install）：
   - `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install`
2) 运行（模板手册方式）：
   - `cd sst_dram_si && export MESH_SIM_TIME=100us && ./tools/run_mesh_with_time.sh`
3) 记录输出目录：
   - 记录 `outputs_large/paper2/dram_mesh_4x4/<timestamp>` 目录名
4) 快速抽查（只看摘要，不翻大日志）：
   - `cat essential_summary_mesh.json`（或用脚本解析）
   - 检查 0.3 中列出的字段是否存在且量级合理
5) 确定性（强烈建议）：
   - 同配置连跑 3 次，比较三次 `essential_summary_mesh.json` 的关键字段应完全一致
6) 若不一致：
   - 第一优先：固定随机源（Step seed / 任何 rand）并确保不依赖 unordered_map 遍历顺序
   - 第二优先：检查是否引入“未定义行为”或“响应 payload 拼装/截断”（例如触发 `[gbi-assert]`）
   - 禁止：用 `use_event_weight_fallback` 之类兜底掩盖问题

---

## 1. 现状审阅（对照目标边界）

### 1.1 已具备的良好地基
- **compute 已模块化**：`compute/ISnnComputeCore.h` + `ISnnComputeCore_SPEC.md`
- **通信子系统雏形已存在**：`services/synapse/route/SpikeCommSubsystem.{h,cc}` + `api/ISpikeTransport.h`
- **权重/窗口相关已开始子系统化**：`services/synapse/weights/WeightMemorySubsystem.{h,cc}`、`services/synapse/weights/SnnBcsrWeightManager.{h,cc}`、`components/GatherBufferIF.{h,cc}`

### 1.2 仍违反目标边界的关键点（需要收敛）
1) **Memory 后端夹带权重语义**
   - 历史问题：旧 `StandardMemBackend` 的 `MemRequestMeta` 含 `is_weight` 与大量 `bcsr_*` 字段（与 Memory 去语义化边界冲突）。
   - 现状：该 legacy 实现已在 Phase5.5 清理删除；主链路统一使用 `services/memory/StandardMemAccess.*`（纯 addr→bytes）。
   - 这使得“内存模块”不可复用，也无法称为“纯地址/字节模块”。
2) **Synapse/Weight 与 Memory 编排缠在一起**
   - 旧实现曾同时承担 pending/解码/缓存/统计（历史问题）；当前主链路已由 `services/memory/StandardMemAccess.*`（纯内存）+ `services/synapse/weights/WeightMemorySubsystem.*`（权重语义）闭环承载。
3) **NoC 与 Route/Synapse 的职责尚未严格分离**
   - Phase2/Phase3 已将“路由构建 + fanout/gating”收敛到 `services/synapse/route/SynapseRouteSubsystem.*`（Synapse/Route 域）。
   - 但 **send/recv/forward/本地投递** 仍主要落在 `components/MultiCorePE.*`，NoC 尚未形成“独立闭环子系统”（Phase4-A1 的核心目标）。
4) **MultiCorePE 仍承载部分 SNN 事务（需要下沉）**
   - Phase3 已将 Step 注入（调度 + BCSR reachability 解析 + 注入）下沉为 `services/stimulus/StepActivationSubsystem.*`（事务域归入 Stimulus；路由依赖 Synapse/Route）。
   - 下一步需要把 **NoC 事务**（send/recv/forward/本地投递 + ring tick）从 `MultiCorePE` 迁出，进一步把 MultiCorePE 收敛为纯装配/调度壳。

### 1.3 目录结构“职责表”（现状）

> 这一节回答“现在项目结构各目录负责什么？”；后续 1.4 给出“最终态应如何合并/拆分”。  
> 注意：这里按**主职责**归类；实际代码仍存在边界污染（见 1.2）。

| 目录 | 当前主职责 | 代表文件/模块 |
|---|---|---|
| `api/` | 跨层稳定接口与最小抽象 | `SnnCoreAPI.h`、`SnnPEParentInterface.h`、`ISpikeTransport.h`、`SnnWeightReader.h` |
| `compute/` | 神经动力学/学习/发放判定（可替换 compute core） | `ISnnComputeCore.h`、`SnnComputeCore.*`、`SnnCoreEngine.*` |
| `control/` | 控制/编排层：GAS/窗口、事务调度、统计汇总 | `SnnPESubComponent*`、`SnnPEApplyScatter.cc`、`SnnPESubComponent_impl.h` |
| `services/` | 可复用服务与子系统（按域拆分，legacy 不进主链路） | `synapse/weights/*`、`synapse/route/*`、`noc/*`、`memory/*`、`legacy/*` |
| `components/` | SST 可加载组件：装配端口/clock/stat；NIC/Loader/内存前端等 | `MultiCorePE.*`、`SnnNIC.*`、`WeightLoader.*`、`GatherBufferIF.*` |
| `events/` | SST Event 类型（Spike、门控等） | `SpikeEvent.*`、`GatingDecisionEvent.*` 等 |
| `docs/` | 设计/重构文档 | `UNIVERSAL_CONTROL_CORE_DESIGN.md` 等 |
| `tests/` | 单元/小型验证（如有） | `tests/*` |

### 1.4 最终态“合并/拆分”映射（现状 → 目标模块）

> 这一节回答“哪些应合并/哪些应拆分/哪些应迁移”。  
> **原则**：先通过接口切割收敛依赖（Phase 1/2），再决定是否需要目录物理搬迁（Phase 4/5）。

#### (A) Memory（纯地址/字节）应该“拆出来”
- **从哪里拆**：
  - `services/legacy/memory/StandardMemBackend.*`：历史 pending/request-id 后端（含权重/BCSR 语义字段），已在 Phase5.5 清理删除（避免边界污染）。
  - `components/GatherBufferIF.*`：作为 Memory 的一种实现/前端（窗口化/聚合属于实现细节）。
- **最终放哪里**（建议）：
  - 接口：`api/IMemoryAccess.h`
  - 实现：`services/memory/StandardMemAccess.*`
  - GatherBufferIF：仍可留在 `components/`（它是可加载 StandardMem 子组件），但其对外边界必须是 `IMemoryAccess`/StandardMem，不得出现权重术语。

#### (B) Synapse/Route（权重/BCSR/ΔV/路由/Step）应该“合并收敛”
- **合并对象（同域）**：
  - 权重语义与缓存：`services/synapse/weights/WeightMemorySubsystem.*`、`services/synapse/weights/WeightCacheOps.*`、`services/synapse/weights/WeightAccessor.*`
  - BCSR 元数据与缓存：`services/synapse/weights/SnnBcsrWeightManager.*`
  - 窗口边集合/累加器：`services/synapse/gas/GasEdgeCollector.*`、`services/synapse/gas/AccumulatorOps.*`
  - 路由构建（从权重导出）：`services/synapse/route/SnnRouteProvider.*`（归入 Synapse/Route，而不是 NoC）
  - Step 注入：已迁移为 `services/stimulus/StepActivationSubsystem.*`（事务域归入 Stimulus；后续可与 `SynapseRouteSubsystem` 共享 BCSR 元信息/数据源以避免口径漂移）
- **最终放哪里**（建议）：
  - `services/synapse/`（或 `services/synapse_route/`）作为“权重+路由”同域模块
  - 对 control 暴露：`api/ISynapseRoute.h`（后续 Phase 2 冻结）
  - 依赖：只能依赖 `api/IMemoryAccess` 与 `compute/ISnnComputeCore`（通过控制层注入回调/接口），不得直接触碰 StandardMem 细节

#### (C) NoC（send/recv/forward）应该“做减法”
- **从哪里拆**：
  - `components/SnnNIC.*`：作为 NoC 的一个 backend（merlin/simpleNetwork）
  - `components/noc/SimpleNetworkWrapper.*`、`components/noc/SnnNetworkAdapter.*`：作为 backend/适配层工具
  - `services/synapse/route/SpikeCommSubsystem.*`：建议保留为 NoC façade，但必须把“路由构建/解析权重”移走，仅保留“封包+发送+门控缓存+本地转发策略”
- **最终放哪里**（建议）：
  - 接口：`api/INocTransport.h`（send/recv/forward）
  - 实现：`services/noc/NocSubsystem.*`（内部组合 SnnNIC、InternalRing、本地投递）
  - 约束：NoC 不得读取 BCSR/权重；fanout 输入必须来自 Synapse/Route

#### (D) NeuralCompute（动力学）保持独立，不与 Memory/NoC 互相污染
- **保持位置**：`compute/`
- **交互方式**：
  - 输入：由 control 或 Synapse/Route 通过 `applySynapticDelta/onSynapticEvent` 喂入
  - 输出：`drainOutputs` → Synapse/Route 决策 fanout → NoC 发送

#### (E) Control 与 Components 的最终收口
- `control/SnnPESubComponent`：只保留“窗口/GAS 编排 + 调用子系统 + 统计汇总”
- `components/MultiCorePE`：只保留“装配/调度/端口连接/统计汇聚”；Step/路由/权重解析全部迁出

---

## 2. 目标架构（最终态依赖方向）

依赖方向：单向依赖，禁止反向 include（否则控制壳会继续膨胀）。

```
components/MultiCorePE (装配/调度/统计汇聚)
  ├─ control/SnnPESubComponent (通用控制子核：GAS 编排/事务调度)
  │    ├─ NeuralCompute (compute/ISnnComputeCore)
  │    ├─ Synapse+Route Subsystem (权重/BCSR/ΔV/路由)
  │    ├─ Stimulus Subsystem (Step 注入/外部刺激)
  │    ├─ NoC Subsystem (send/recv/forward)
  │    └─ Memory Subsystem (read/write bytes)
  └─ components/SnnNIC (NoC 后端实现之一：merlin/linkcontrol)
```

### 2.1 五个子系统对外接口（建议）

> 这里只定义职责与接口形状，具体函数名可在 Phase 1 落地时再冻结。

#### (A) Memory：`IMemoryAccess`（纯地址/字节）
- `read(uint64_t addr, size_t bytes, Callback cb) -> req_id`
- `write(uint64_t addr, span<uint8_t> data, Callback cb) -> req_id`
- `handle(StandardMem::Request*)` / 或内部接管 StandardMem handler
- 可选能力：对齐读/切片、聚合（GatherBufferIF 作为实现细节）
- **禁止出现**：weight / synapse / bcsr 等术语与字段

#### (B) Synapse+Route：`ISynapseRoute`（权重语义 + 路由语义）
- 权重读取/ΔV 产生：
  - `recordEdge(pre_global, post_local, count)`（窗口模式）
  - `issueReads()` / `onMemData(...)`（由 Memory 回调驱动）
  - `emitDeltasToCompute()`（把 ΔV 提交到 `ISnnComputeCore`）
- 路由：
  - `buildRoutes()`（从 BCSR/权重元数据构建路由表；可缓存/共享）
  - `fanout(source_global) -> span<dest_global>`（只做选择，不发送）

#### (C) Stimulus：`StepActivationSubsystem`（注入时基 + 选源 + 注入）
- 目标：把 Step/外部刺激的**时基与注入事务**从 Synapse/Route 与 MultiCorePE 中剥离出来，避免与窗口/GAS 时钟节奏耦合。
- 入口（与现有实现对齐）：
  - `tick(now_cycle)`：固定周期注入（`step_activation_period_cycles>0`）与 pending 注入处理
  - `onBeginGather(seq, ts_ns, core_id)`：legacy BeginGather 触发（`period_cycles==0`）
  - `onEndScatter(seq)`：可选 `reset_membranes`（`step_reset_mem_each_step=1`）
- 依赖方向：Stimulus →（可选）Synapse/Route（fanout/可达性）→ NoC；不反向依赖 control 实现细节。
- 现状备注：当前 `step_activation_use_bcsr_routes=1` 的 reachability 解析仍由 Step 子系统自持；后续建议与 `SynapseRouteSubsystem` 共享 BCSR 元信息以避免口径漂移。

#### (D) NoC：`INocTransport`（只做 send/recv/forward）
- `send(SpikeEvent*)`（接管生命周期）
- `deliverLocal(SpikeEvent*)`（本 PE 内转发到目标 core）
- `pollRecv()` / callback handler（来自 NIC/LinkControl）
- **禁止出现**：fanout/weight-driven route 选择逻辑（路由由 Synapse/Route 给出）

#### (E) NeuralCompute：`ISnnComputeCore`（已存在）
- `applySynapticDelta / endCycle / drainOutputs / updateNeuronStates` 等
- **禁止直接触碰**：StandardMem / NoC / 路由表（通过控制层与子系统交互）

---

## 3. 增量迁移路线（每步 100us 回归）

### Phase 0：冻结基线 + 回归脚本标准化（0 行为变更）
- 目标：任何后续重构都能“拿同一套命令”做 100us 判定
- 动作：
  - 明确 baseline run 的统计口径与必查字段（见 0.3）
  -（可选）在 SnnDL `docs/` 里补一页“回归检查清单”，只列字段与命令
- 回归：100us ×3（必须稳定）

### Phase 1：抽出纯 Memory 接口（不改 Synapse 行为）
- 目标：把“地址/字节读写 + pending”从权重语义中剥离
- 动作（建议最小实现）：
  1. 新增 `api/IMemoryAccess.h`
  2. 新增 `services/memory/StandardMemAccess.{h,cc}`（实现 IMemoryAccess；内部持有 `StandardMem` 指针与 pending map）
  3. 让现有 `WeightMemorySubsystem` **通过 IMemoryAccess 发起读**，而不是直接依赖 `StandardMemBackend/MemRequestMeta(bcsr_*)`
  4. legacy：旧 `StandardMemBackend` 已在 Phase5.5 删除；避免保留“带权重语义”的 Memory 后端参考实现
- 验收：
  - 100us 回归通过
  - 主路径统一为 `services/memory/StandardMemAccess.*`（并保持 fail-fast 断言式诊断）

#### Phase 1 任务清单（可执行，建议按顺序）
1) **冻结纯内存接口（不引入权重语义）**
   - [ ] 新增 `api/IMemoryAccess.h`：
     - `using ReadCallback = std::function<void(uint64_t req_id, uint64_t addr, std::vector<uint8_t>&& data)>;`
     - `uint64_t read(uint64_t addr, size_t bytes, ReadCallback cb);`
     - `uint64_t write(uint64_t addr, const std::vector<uint8_t>& data, std::function<void(uint64_t)> cb);`
     - 约束：`bytes>0`；失败语义按 5.2 冻结
2) **实现 StandardMemAccess（pending 与回包分发归一处）**
   - [ ] 新增 `services/memory/StandardMemAccess.h/.cc`：
     - 仅记录 `addr/size +（可选）对齐/切片信息 + 回调`
    - 允许内部自建 pending map（主链路已不再依赖 legacy `StandardMemBackend`）
     - **不得**出现任何 `weight/synapse/bcsr` 字段或命名
3) **把“对齐读/切片读”统一收敛到 Memory 层**
   - [ ] 将“cacheline 对齐扩展 + slice_offset”逻辑从权重路径搬到 `StandardMemAccess`
   - [ ] 保留现有诊断：可在 Memory 层提供 `diag_mem_read`（仅 addr/bytes/resp_bytes，不输出权重内容）
4) **让 Synapse/Weight 子系统只依赖 IMemoryAccess**
   - [ ] `WeightMemorySubsystem`（后续会重命名为 Synapse/Route）改为通过 `IMemoryAccess::read` 发起请求
   - [ ] 子系统内部维护 `req_id -> 语义元数据` 的映射（例如 BCSR rowptr/colidx/blockdata 的解析上下文），但这份映射必须留在 Synapse/Route，而不是 Memory
5) **去语义化 StandardMemBackend（或逐步退场）**
   - [x] legacy `services/legacy/memory/StandardMemBackend.*` 已在 Phase5.5 删除（避免继续维护带权重语义字段的 Memory 后端参考实现）
6) **回归与确定性验收**
   - [ ] 100us ×3：关键字段完全一致（见 0.3）
   - [ ] 日志验证：不得出现 `[gbi-assert]`；`diag-bcsr-colidx-dump` 不得出现 0/脏字节
   - [ ] 若出现偏移：回滚到 Phase 0 稳定点，缩小改动面再推进

### Phase 2：Synapse/Route 子系统收敛（权重/BCSR/路由同域）
- 目标：形成一个“闭环”的 Synapse/Route 子系统，对 control 提供稳定入口
- 动作：
  1. 将 `WeightMemorySubsystem` 重命名/重定位为 `SynapseRouteSubsystem`（或拆成 `SynapseWeightSubsystem + RouteSubsystem` 两个类，但仍同模块目录）
  2. 路由构建/共享缓存从 `services/synapse/route/SpikeCommSubsystem` 下移到 `services/synapse/route/SynapseRouteSubsystem`
  3. `services/synapse/weights/SnnBcsrWeightManager` 的 rowptr/colidx/block 缓存由 Synapse/Route 统一调度
- 回归：100us ×3，关键字段一致

### Phase 3：已完成（fanout/gating 下沉 + Step 注入下沉）
- 目标：进一步压缩 MultiCorePE 的“事务逻辑面”，为 NoC 子系统化铺路。
- 达成：
  - `services/synapse/route/SpikeCommSubsystem` 已退化为 transport façade（fanout/gating 委托 `services/synapse/route/SynapseRouteSubsystem`）；
  - Step 注入已下沉为 `StepActivationSubsystem`，MultiCorePE 仅转发 tick/阶段事件与注入回调；
  - 10us/100us 回归确定性通过（见 6.4）。

### Phase 4：NoC 子系统全覆盖（A1：send/recv/forward + 本地投递）
- 目标：NoC 形成独立闭环子系统，覆盖：外发/收包/转发 + 本地投递 + ring tick/receive；MultiCorePE 仅保留“后端装配 + 生命周期/统计聚合”。
- 设计：`docs/NOC_SUBSYSTEM_DESIGN.md`
- 动作（建议两段式，先适配器再搬迁）：
  1. 新增 `services/noc/NocSubsystem.{h,cc}`（先做编排层）：统一收敛输入队列与解包，并通过回调调用 MultiCorePE 的 backend 能力（低风险、易回归）。
  2. 稳定后把 ring tick/receive、NIC 外发等后端逻辑逐步迁入 NoC 子系统，并精简 `MultiCorePE` 内相关函数与状态。
- 回归：每一步 10us→100us；同配置 100us 至少 2 次关键字段完全一致。

### Phase 5：收尾清理（移除 legacy 分支，冻结接口）
- 目标：减少“旧接口/旧路径”长期拖累
- 动作：
  - 删除/封存不再使用的旧 pending 结构与旧接口
  - 统一 include 边界（禁止 services 直接 include control 私有头）
  - 文档更新：把最终接口写入 `api/README.md` 并补一页“模块职责表”
- 回归：100us ×3

---

## 4. 进度记录与协作约定

- 每完成一个 Phase：
  - 在本文件末尾追加“已完成项/对应 run_dir/关键指标摘要”
  - 确保 `make -j4 && make install` + 100us 回归记录可复现
- 若出现行为偏移：
  - 优先回退到上一 Phase 的“最后一个稳定点”，再做更小的拆分推进

---

## 5. 待主人确认的关键点（只问一个问题喵）

已确认（主人选择 A）：Phase 1 的 `IMemoryAccess` **读回调数据形态采用 `std::vector<uint8_t>`**，直接复用 `StandardMem::ReadResp::data`，避免生命周期复杂度喵～ (๑•̀ㅂ•́) ✧

### 5.1 Phase 1：`IMemoryAccess` 接口草案（冻结口径 v0）

> 注意：这里的 “Memory” 只承诺 **地址→字节块**。任何 `weight/synapse/bcsr` 语义都必须留在 Synapse/Route 子系统。

- 请求：
  - `read(addr, bytes, cb)`：异步读取，回调拿到 `std::vector<uint8_t>`（可能为空表示失败，或另行引入 status，见 5.2）
  - `write(addr, data, cb)`：异步写入
- 回调（建议形态）：
  - `cb(req_id, addr, std::vector<uint8_t>&& data)`
- 允许实现细节：
  - 对齐读/切片读（例如 cacheline 对齐扩展后再切片回调）
  - 与 `components/GatherBufferIF` 组合（GAS/窗口化/聚合属于实现细节，但仍不得引入权重语义）

### 5.2 仍需主人确认（错误语义）

已冻结为 **A**：失败用 `data.empty()` 表示，且接口层明确禁止 `bytes==0`；实现见：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IMemoryAccess.h`

---

## 6. 进度记录（摘要）

### 6.1 已完成：Step+BCSR 非确定性根因修复（GatherBufferIF 大读分片 + fail-fast）
- 根因：`size>cacheline` 的大读穿过 `memHierarchy.Cache`（`coherence_protocol=none`）时回包 payload 可能脏/截断，导致 BCSR 解析为 0/垃圾 → ΔV≈0 → 发放异常且非确定性。
- 修复：`components/GatherBufferIF.cc` 下游按 cacheline 分片读并在 SRAM 拼接；若任一分片 `resp_bytes < frag_sz` 立刻 fatal（断言式诊断）。
- 100us ×3（同配置完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251223-144549`、`20251223-144725`、`20251223-144833`

### 6.2 已完成：Phase1（Memory 去语义化：IMemoryAccess / StandardMemAccess）
- 规划：以 `docs/UNIVERSAL_CONTROL_CORE_DESIGN.md`、`docs/plans/2026-01-03-universal-core-completion.md` 与 `sst_dram_si/TECH_PROGRESS.md` 的落地记录为准
- OpenSpec：`openspec/changes/refactor-snndl-phase1-memory-access/`
- 100us ×3（同配置完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251223-163433`、`20251223-163612`、`20251223-163713`

### 6.3 已完成：Phase2（Synapse/Route 收敛：路由构建从 SpikeCommSubsystem 下移）
- 规划：以 `docs/UNIVERSAL_CONTROL_CORE_DESIGN.md`、`docs/plans/2026-01-03-universal-core-completion.md` 与 `sst_dram_si/TECH_PROGRESS.md` 的落地记录为准
- OpenSpec：`openspec/changes/refactor-snndl-phase2-synapse-route/`
- 关键改动：
  - 新增 `services/synapse/route/SynapseRouteSubsystem.{h,cc}`：接管“路由构建/共享缓存/BCSR route 解析”
  - `SpikeCommSubsystem::initRouting()` 仅委托 `synapse_route_->initRoutes()` 并消费 routes
- 回归验证（seed=314159）：
  - baseline 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251223-172019`
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251223-174607`
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251223-174703`（关键字段与 baseline 完全一致）

### 6.4 已完成：Phase3（fanout/gating 下沉 + Step 注入下沉）
- 关键改动（摘要）：
  - fanout/gating 下沉至 `services/synapse/route/SynapseRouteSubsystem.*`；`services/synapse/route/SpikeCommSubsystem.*` 退化为 transport façade。
  - Step 注入下沉至 `services/stimulus/StepActivationSubsystem.*`；MultiCorePE 仅转发 tick/阶段事件。
- 回归验证（seed=314159，use_bcsr_routes=1）：
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-000114`
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-000249`
  - 100us（同配置重复 1 次完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-000446`

### 6.5 已完成：Phase4（NoC 子系统全覆盖 + INocTransport 接口化）
- Phase4-A1.1（NoC 编排层）：`services/noc/NocSubsystem` 统一收敛 send/recv/forward + 本地投递（后端仍可复用 MultiCorePE 现有能力）。
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-093307`（`neurons_fired_total=5`）
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-093407`
  - 100us（同配置重复 1 次完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-093512`
- Phase4-A1.2（NoC 后端实现搬迁，真正闭环）：ring tick/receive + 外发/中继逻辑迁入 `services/noc/NocSubsystem`，MultiCorePE 更壳化。
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-103032`（`neurons_fired_total=5`）
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-103128`
  - 100us（同配置重复 1 次完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-103231`
    - `neurons_fired_total=12854`、`gas_scatter_spikes_emitted_total=406`、`window_spikes_total=812`、`step_activation.invocations=51`
- Phase4-A1.3（接口化：Control/Step 只调用 NoC 接口）：新增 `api/INocTransport` + `api/NocSpikeTransport`，并将 Control/Step 接入。
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-105709`（`neurons_fired_total=5`）
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-105808`
  - 100us（同配置重复 1 次完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-105912`
    - `neurons_fired_total=12854`、`gas_scatter_spikes_emitted_total=406`、`window_spikes_total=812`、`step_activation.invocations=51`

### 6.6 已完成：Phase6（Stimulus 域：StepActivationSubsystem 目录归位）
- 关键改动：将 Step 子系统从 `services/StepActivationSubsystem.*` 移动到 `services/stimulus/StepActivationSubsystem.*`，并补齐 Makefile 对子目录的 depfiles/dirstamp 支持，确保 `make -j4` 稳定可复现。
- 回归验证（100us）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251224-145051`
  - `neurons_fired_total=12854`、`gas_scatter_spikes_emitted_total=406`、`window_spikes_total=812`、`step_activation.invocations=51`

### 6.7 已完成：Phase7（MultiCorePE 进一步壳化：外部 SpikeEvent 直注入下沉 Stimulus + 禁止 legacy requestMemoryAccess）
- 关键改动：
  - 新增 `services/stimulus/ExternalSpikeInputSubsystem.{h,cc}`：兼容 `external_spike_input` 端口直接注入 `SpikeEvent*` 的 legacy 语义（**仅本地投递**；不 relay/forward）。
  - `components/MultiCorePE`：`handleExternalSpikeEvent()` 的 SpikeEvent 分支改为委托 `ExternalSpikeInputSubsystem::onSpike()`；MultiCorePE 只保留装配/转发。
  - `components/MultiCorePE`：删除未挂接的 `handleMemoryResponse/pending_memory_requests_` 旧壳；`requestMemoryAccess()` 改为 fail-fast `fatal`（强制走 `IMemoryAccess`+`synapse/weights` 链路，避免边界回退）。
- 回归验证：
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251228-172153`（`neurons_fired_total=1`；`gas.*_p95` 非 0）
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251228-172308`（`neurons_fired_total=2220`）
  - 100us（同配置重复 1 次完全一致）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251228-172437`（关键字段与上一条完全一致）

### 6.8 已完成：Phase8（NoC Spike packet 严格收敛：MultiCorePE 不再走 deliverSpike fallback）
- 目标：
  - 平台层（`components/MultiCorePE`）对 `NocPacketKind::Spike` **不再**做任何 `SpikeEvent` 语义处理；
  - 所有 NoC 收到的 Spike 输入必须通过 `core->deliverPacket(NocPacketEvent*)` 进入 core/workload，由 workload 负责解码与处理；
  - 禁止 `SpikePacketBridge::deliverPacketToEndpoint()->core->deliverSpike()` 这条 legacy 回退（避免边界回退带来语义漂移与非确定性风险）。
- 关键改动：
  - `components/MultiCorePE`：在 `deliverPacketToEndpoint_()` 中对 `kind==Spike` 改为 strict 调用 `cores_[endpoint_id]->deliverPacket(pkt)`；若 core 未接管则 `fatal`（fail-fast）。
- 回归验证（mesh 模板方式）：
  - 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-034134`（`neurons_fired_total=1`；`gas.*_p95` 非 0）
  - 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-034247`（`neurons_fired_total=2220`；`gas.*_p95` 非 0）

### 6.9 已完成：Phase9（9.1–9.4：CoreShellAPI 槽位 + packet-first 注入 + 退役 deliverSpikeToCore）
- 目标（一次性完成 9.1–9.4）：
  - 9.1：核心槽位 API 切换为 `CoreShellAPI`（平台层不再直接依赖 `SnnCoreAPI`）
  - 9.2：ExternalSpikeInputSubsystem 注入改为 packet-first（走 `INocTransport`）
  - 9.3：StepActivationSubsystem 注入改为 packet-first（走 `INocTransport`）
  - 9.4：退役 `deliverSpikeToCore()`（主链路不再走 `deliverSpike` 回退）
- 关键改动：
  - `components/MultiCorePE.*`：`coreX` 槽位按 `CoreShellAPI` 加载；为“core 未加载/不匹配 API”加入 fail-fast `fatal`，避免静默归零。
  - `control/SnnPESubComponent.h`：ELI 注册父接口改为 `CoreShellAPI`，确保能被 `loadAnonymousSubComponent<CoreShellAPI>` 正确加载（修复 Phase9 初版导致 core 为空→Step 不触发→全链路归零的问题）。
  - `services/stimulus/ExternalSpikeInputSubsystem.*`：`SpikeEvent*` → `SpikeNocCodec::encode` → `noc->injectLocal/sendExternal`。
  - `services/stimulus/StepActivationSubsystem.*`：同上，注入链路完全 packet-first。
  - `components/MultiCorePE.*`：删除 `deliverSpikeToCore()` 及其绑定；仅保留 legacy-only 入口通过 `dynamic_cast<SnnCoreAPI*>` 调用（用于 reset/forceEndGather）。
- 回归验证（脚本保持不改，按模板启动；stream 通过环境变量选择）：
  - SNN 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-050427`（`neurons_fired_total=1`；非 0）
  - SNN 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-050009`（`neurons_fired_total=2220`；与稳定基线量级一致）
  - stream 10us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-050241`（`memory_requests` 非 0；WeightLoader 显示 `workload_impl=stream -> skip`）
  - stream 100us：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260103-050541`（`memory_requests=79920`、`external_spikes_sent/received=3980`）
