# SRAM Modeling Deep-Dive Design

**Goal:** 基于当前 `SnnDL` 已有的 SRAM timing 第一阶段实现，系统梳理 `state SRAM / weight_idx SRAM / weight_l0 SRAM` 的现状、主要不足与长线演进路线，为后续分阶段实现提供统一设计基线。

## 1. 当前现状（As-Is）

### 1.1 配置与入口链路

当前 SRAM 建模已经具备完整的 **spec-first -> runtime -> effective_config -> C++ 参数** 链路：

- 顶层仿真入口仍是 `sst_dram_si/test_mesh_4x4.py`，实际运行由 `mesh_template.entry` / `mesh_template.runtime` 组装。
- spec schema 本身没有一等 `sram` 顶层键；在 spec-first 场景下，SRAM 主要通过：
  - legacy `state`/`mesh_cfg["sram"]` 默认链路，或
  - `components["pe.core"]` / `overrides.match.role="pe.core"`
  对最终 core 参数做覆盖。
- `build.py` 会把结构化的 `mesh["sram"]` 写入 `effective_config.json`，但 **晚于此时应用的 `components.pe.core` overrides 并不会回写 `effective_cfg["sram"]` 摘要本身**；它们只会出现在 `overrides` / `overrides_report` 中。

这意味着：**SRAM 参数已经“能传到 C++”，但 provenance 表达并不统一**。对分析者而言，`effective_config.json["sram"]` 与实际生效的 `pe.core` 参数之间仍存在认知鸿沟。

### 1.2 当前 SRAM 模型本体

统一的底层模型是 `services/memory/sram_sim/model/BankedSramModel`：

- 输入：`banks / ports_per_bank / bank_interleave_bytes / t_read_cycles / t_write_cycles / sample_log2`
- 行为：逐拍累加每个 bank 的读写访问数；若 `reads+writes > ports_per_bank`，则计算 `over = total - ports`，再乘以按读写平均服务时间估出的 `extra_cycles`
- 输出：
  - `reads/writes/bytes`
  - `bank_conflict_ticks_total`
  - `predicted_extra_cycles_total`
  - `resident_bytes_peak`
  - 内部还保留 `bank_conflict_events_total`、`bank_peak_accesses_per_tick`、`energy_*_pj_total`

它本质上仍是 **pressure proxy**，不是显式本地 SRAM 控制器：

- 没有逐请求队列
- 没有真实读写仲裁顺序
- 没有 read/write turnaround
- 没有 miss/refill 或结构元数据成本
- `bulk` 模式下还会把访问均匀 round-robin 分摊到各 bank

### 1.3 当前 timing 闭环（第一阶段）

当前已经完成“observe-only -> stall budget”的第一阶段闭环：

- `state SRAM`：
  - 在 `SnnComputeCore` 内部配置并消费 `BankedSramModel`
  - 每拍取出 `consumeLastCyclePredictedExtraCycles()` 累加到 `state_sram_stall_budget_`
  - 当 budget > 0 时，阻塞 `endCycle()` / `endCycleCandidates()` 的状态推进
- `weight SRAM`：
  - 在 `WeightMemorySubsystem` 内部维护 `idx_sram_model_` 与 `l0_sram_model_`
  - 每拍把两者 `predicted_extra_cycles` 合并到 `weight_sram_stall_budget_cycles_`
  - 当 budget > 0 时，直接跳过新的 prefetch / deferred drain / direct issue

这说明当前模型 **已经会改变执行时序**，不再只是离线统计器。但它仍是 **“整拍 budget 阻塞”**，不是对单条本地 SRAM 请求做细粒度排队和完成通知。

### 1.4 当前验证状态

已有证据可以把现状分成三块：

1. **基础模型层**：
   - `test_banked_sram_model` 已验证“同 bank 冲突 -> 非零 extra cycles；跨 bank -> 0”
2. **历史 full-system A/B**：
   - `GCSSIDX2` 路径已看到 `weight_idx` 与 `state` 非零，且 ON/OFF 语义守恒
3. **当前独立 smoke**：
   - `snndl-thing-exp/runs/sram_timing_smoke/20260308-191049/validation.log` 已 `fail=0 warn=1`
   - 但该 smoke 的 `sram` 摘要显示：
     - `state.*` 非零
     - `weight_idx.* = 0`
     - `weight_l0.* = 0`

结论很明确：**state SRAM 已经有独立可回归覆盖；weight_idx 只在历史 GCSSIDX2 样本中有证据；weight_l0 到目前仍缺非零有效样本。**

## 2. 主要不足（Gap Analysis）

### 2.1 配置与 provenance 不统一

这是当前最容易埋坑的一点：

- spec-first 没有一等 `sram` schema
- 用户经常通过 `components.pe.core.*` 直接改 SRAM 参数
- `effective_config["sram"]` 摘要来自 `mesh["sram"]`，与后续 override 后的真实生效值不总一致

这会导致：

- 运行时可工作
- 但回看 run 产物时，分析者难以第一眼确认“到底哪个 SRAM 参数生效了”

这不是功能 bug，但已经是 **实验 reproducibility / provenance bug**。

### 2.2 模型 fidelity 仍偏粗

#### State SRAM

当前 `state SRAM` 的真实流量建模仍然很粗：

- `applyPendingDeltas_()` 与 `updateNeuronStates()` 主要使用 `noteBulkUniform()`
- 大量 state 访问被“均匀撒到各 bank”
- `VirtualSramLayout` 虽然定义了 `vmem/refrac/last_spike` 地址空间，但 state 路径并没有逐地址落到该布局
- resident bytes 已把 `last_spike` 算进容量，但流量侧没有对 `uint64_t last_spike` 单独计费

因此：**state SRAM 现在更像“phase 级 bulk pressure estimator + timing penalty”，而不是 layout-aware state memory simulator。**

#### Weight SRAM

`weight_idx` 与 `weight_l0` 的精度也不对称：

- `weight_idx` 已经是逐地址 noteRead 口径，精度明显高于 state
- 但 resident bytes 直接拿“索引文件大小”近似，不是运行时结构真实 footprint
- `weight_l0` 目前并不是“通用 weight local cache”，而是 **idx2 ingress value cache 的实验缓存镜像**
- 功能缓存本体仍是 `unordered_map + deque`；SRAM 模型只对 lookup/fill/evict 做旁路记账
- `weight_l0` 的 resident bytes 只算 value payload，不含 tag / metadata / replacement 结构成本

因此：**weight L0 还不是 architecture-level local SRAM cache，只是某条实验路径上的功能缓存 + SRAM pressure mirror。**

### 2.3 timing 反馈过于粗粒度

当前两侧 timing 闭环都采用同一种策略：

- 每拍读出上一拍 `predicted_extra_cycles`
- 累加成一个 budget
- 之后每拍 `budget -= 1`

问题在于：

- 无法区分 gather/apply/scatter/retire 哪个 phase 被卡
- 无法区分 state / idx / l0 哪种 array 是主因
- 无法表示“同拍部分操作可继续、部分操作必须等”
- 无法把某个 miss/fill 绑定到特定 callback 完成时刻

换句话说，当前已经从“完全 observe-only”迈出一步，但仍停留在 **global stall bucket**，还没有进入 **local SRAM request timing**。

### 2.4 统计链不完整

虽然底层 `BankedSramModel` 里已经有：

- `bank_conflict_events_total`
- `bank_peak_accesses_per_tick`
- `energy_read_pj_total`
- `energy_write_pj_total`

但当前 PE 聚合 / summary 并没有把这些暴露出来。

更关键的是：

- `core_state_sram_stall_cycles_total` 已在 core/workload 内存在
- weight 侧也已有内部 `weight_sram_stall_budget_cycles_`
- 但用户最终看到的 summary 里仍缺“**真正被执行时序消耗掉的 stall cycles**”

这会导致现在能回答“预测冲突有多少”，却还不方便回答“**真实因为 SRAM 被 stall 了多久**”。

### 2.5 验证矩阵不完整

目前验证呈现明显断层：

- `state`：有 smoke + 历史 full-system A/B
- `weight_idx`：有历史 GCSSIDX2 full-system A/B
- `weight_l0`：无非零历史样本
- `mixed state+weight`：只有开关，不足以证明三类数组同时被合理覆盖

所以当前最大风险不是“state 路径完全没做”，而是：

- **weight_l0 缺证据**
- **weight 路径缺独立最小回归 case**
- **mixed traffic 下的相互作用还没有被系统验证**

## 3. 备选演进路线

### 路线 A：增量式 proxy-evolution（推荐）

思路：保留 `BankedSramModel` 作为统一底座，不推翻现有接口，只逐步提高 fidelity。

阶段式推进：

- 先补 provenance 与统计闭环
- 再给 `weight_l0` 一个显式 local cache 语义
- 再把 state 路径从 bulk uniform 升级到 layout-aware chunked access
- 最后再考虑统一成 PE 内部的 local SRAM fabric

优点：

- 与当前代码最兼容
- 风险最小
- 易于逐阶段验证

缺点：

- 中间阶段会长期存在“state/weight 精度不对称”
- 架构形态不如一次性重写干净

### 路线 B：直接做完整 local SRAM controller

思路：为 `state/idx/l0` 建显式 request queue / bank scheduler / completion callback。

优点：

- 模型最干净
- timing 语义最强
- 后续能耗/面积/arbiter 研究空间最大

缺点：

- 改动面大
- 与当前 compute / weight / workload 耦合深
- 很容易破坏现有可回归行为
- 不符合当前仓库“最小侵入、兼容优先”的节奏

### 路线 C：继续停留在离线观测与后处理

思路：不再增强 runtime timing，只做统计与 summary。

优点：

- 成本最低
- 几乎不碰执行语义

缺点：

- 不能回答真正的 architecture timing 问题
- 与当前“我们要深入建模 SRAM”的目标相矛盾

**推荐结论：选路线 A。**

它最符合当前仓库节奏：在不重写大系统的前提下，把当前已有的一阶段闭环逐步推进到“可解释、可验证、可扩展”的工程状态。

## 4. 推荐长线规划（Recommended Roadmap）

### Phase 0：配置与观测收口（短期，必须先做）

目标：先把“我们到底在测什么”说清楚。

建议项：

1. 在 spec schema 中引入一等 `sram` 顶层（保持 `components.pe.core` 兼容）
2. 让 `effective_config.json` 同时输出：
   - 结构化 `sram` 摘要
   - 最终生效的 `pe.core` SRAM 参数快照
3. 将以下统计正式上抛到 PE/summary：
   - `state_sram_enforced_stall_cycles_total`
   - `weight_sram_enforced_stall_cycles_total`
   - `weight_idx_sram_bank_peak_accesses_per_tick`
   - `weight_l0_sram_bank_peak_accesses_per_tick`
   - `core_state_sram_bank_peak_accesses_per_tick`
4. 统一 README / ELI 注释，把“Observe-only”旧措辞收口，明确哪些字段已进入 timing，哪些仍只是 observability

**交付标准：** 跑一次 run 后，用户只看 `effective_config.json + essential_summary_mesh.json` 就能明确当前 SRAM 的真实生效配置与真实 stall 成本。

### Phase 1：把 weight 路径验证补齐（短中期）

目标：让 `weight_idx` / `weight_l0` 都具备独立回归证据。

建议新增实验：

1. `state_sram_debug`
   - 低 fanout、弱 weight 活动，专门看 state
2. `weight_idx_sram_debug`
   - GCSSIDX2 / pre-MPHF 触发高密度 index lookup
3. `weight_l0_fill_smoke`
   - 专门命中 experimental idx2 ingress cache，确保 `lookup/hit/fill/evict` 全非零
4. `sram_mixed_smoke`
   - 同时让 state 与 weight 都有稳定非零 traffic

**交付标准：** `snndl-thing-exp/cases/` 下至少有一条能稳定让 `weight_idx` 非零，一条能稳定让 `weight_l0` 非零，一条 mixed case 能同时非零。

### Phase 2：把 weight L0 从“镜像统计”升级成显式 local cache（中期）

目标：让 `weight_l0` 从实验功能缓存真正变成架构对象。

建议：

- 明确 `weight_l0` 的 cacheline/slot/tag 语义
- resident bytes 统计纳入 tag/meta 成本
- 替换策略与冲突行为与 SRAM 模型对齐
- 让 lookup/fill/evict 的 timing 与功能状态统一，而不是“功能用哈希表，SRAM 只旁路记账”

**交付标准：** `weight_l0` 的命中率、驻留量、fill/evict、stall 之间具备一致解释，不再只是 experimental side-cache。

### Phase 3：state SRAM 升级为 layout-aware chunk timing（中期）

目标：把 state 从 bulk proxy 升成可解释的 phase/chunk 级模型。

建议：

- 用 `VirtualSramLayout` 真正驱动 `vmem/refrac/last_spike` 的地址访问
- 把 `applyPendingDeltas_()` / `updateNeuronStates()` 拆成 chunk 级 micro-op
- 允许不同 state field 有不同 bytes / 访问频率
- 让 `last_spike` 的流量成本进入 timing，而不仅是容量

**交付标准：** state 路径不再只依赖 `noteBulkUniform()`；bank conflict 与 layout/field traffic 有可追溯映射。

### Phase 4：从“budget 阻塞”走向“local SRAM service contract”（中长期）

目标：把当前粗粒度 budget 演进成局部服务契约，但不必一步到位做完整 controller。

建议采用折中形态：

- 保留 `BankedSramModel` 作为 banked service estimator
- 为上层暴露一个轻量 request contract：
  - `submit(array_kind, bytes, addr, phase, context)`
  - 返回 `ready_after_cycles` 或 `token`
- compute / weight 侧根据返回值安排 phase progression，而不是统一塞进全局 budget

这比完整 local controller 更稳，但比当前 “每拍减 1” 明显更精确。

### Phase 5：校准、能耗与论文口径（长期）

目标：把 SRAM 建模从“能跑能解释”推进到“能做 architecture study”。

建议：

- 将 `energy_read_pj / energy_write_pj` 从模型内部字段接入 spec/build/summary
- 明确 `calib_meta` 不只是 provenance，而是真正可参与参数注入的校准入口
- 为不同数组（state / idx / l0）建立可切换的工艺/配置 profile
- 在 summary 中增加：
  - `energy_read_pj_total`
  - `energy_write_pj_total`
  - `stall_cycles_per_k_access`
  - `effective_bw_bytes_per_cycle`

## 5. 建议的近期优先级

如果只排最近 3 个最值得做的动作，建议顺序是：

1. **先补 Phase 0 的 provenance + enforced stall counters**
   - 这是所有后续分析的地基
2. **再补 Phase 1 的 `weight_idx` / `weight_l0` 独立 case**
   - 没有 coverage，就无法判断模型是否真的工作
3. **然后做 Phase 2 的 `weight_l0` 显式 cache 升级**
   - 这是当前最明显的 fidelity 缺口

而 `state` 的更细粒度 layout-aware 升级，可以排在 weight L0 之后。原因是 state 路径虽然粗，但已经有真实非零覆盖；weight L0 目前还停在“几乎没有架构证据”的阶段。

## 6. 成功判据（Success Criteria）

我们可以用以下标准判断 SRAM 建模是否真正“进入下一阶段”：

1. **配置可信**：`effective_config` 能无歧义表达真实生效的 SRAM 参数
2. **统计可信**：summary 同时有 predicted 与 enforced stall 两类指标
3. **覆盖完整**：state / weight_idx / weight_l0 / mixed 都有稳定 regression case
4. **模型可解释**：每条 stall 都能回溯到具体 array 与 phase
5. **长线可扩展**：后续能自然接入能耗与 calibration，而不需要推倒重来

## 7. 结论

当前 SRAM 建模已经不是空白：

- 配置链路存在
- 第一阶段 timing 闭环已打通
- state 与部分 weight_idx 证据已经成立

但它距离“成熟的 architecture SRAM model”还差三步：

1. **把 provenance 和 observability 补齐**
2. **把 weight L0 从实验缓存镜像升级成显式本地 cache**
3. **把 state/weight 的 timing 从 global budget 提升到 phase-aware local service**

因此，后续最合理的路线不是推翻重做，而是沿着当前 `BankedSramModel + phased closure` 继续演进，逐步把它从“可用代理模型”推进到“可发表、可解释、可扩展的 SRAM architecture model”。
