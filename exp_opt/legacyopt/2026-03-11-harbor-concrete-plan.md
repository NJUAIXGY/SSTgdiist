# HARBOR 具体落地方案：从 Core-Local TAT 到 PE-Local Memory x NoC Bridge

> 日期：2026-03-11  
> 状态：具体设计方案（仅设计，不改主线语义）  
> 基线：`full_system_baseline = DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter`

## 0. 一句话结论

当前主线的 `step=1` 冒烟统计已经给出一个非常明确的边界：

- `gas_harbor_window_line_lb_total = 150907`
- `memctrl.req_total = 150907`

这意味着，在 **当前 `dstcore + GCSS-GLIDE` 存储口径** 下，`WeightMemorySubsystem` 看到的 DRAM 请求数已经基本贴住了 line-level lower bound。  
因此，下一步不应该继续在现有 WMS 地址整形里“硬抠更少的 request”，而应该把优化层次前移到接收侧：

- 不要再走 `token -> edge flood -> addr rebuild`
- 而要让 `STORM` 的 `pre token` 共享语义尽量延续到 memory service 入口

据此，HARBOR 的具体落地必须分成两个阶段：

1. **Phase A / HARBOR-TAT-Core**
   - 基于当前代码结构可直接落地
   - 目标是消掉接收侧对象膨胀，建立证据链
   - 预期不显著改变 `memctrl.req_total`

2. **Phase B / HARBOR-PE**
   - 引入真正的 PE 级桥接单元和 `dstpe` 存储口径
   - 这是第一阶段有机会进一步压低 `memctrl.req_total` 的方案

换句话说：

- **Phase A 是“证明层 + 稳定中间层”**
- **Phase B 才是“真实 memory x NoC 收益层”**

---

## 1. 现状与瓶颈定位

## 1.1 当前关键代码路径

今天的接收侧主线实际走的是下面这条链路：

1. `MultiCorePE::deliverPacketToEndpoint_()`
   - `components/MultiCorePE.cc`
   - 按 `endpoint_id` 把包直接送到某一个 core：`cores_[endpoint_id]->deliverPacket(pkt)`

2. `SnnWorkload::deliverPacket()`
   - `services/workload/snn/SnnWorkload.cc`
   - 对 `SpikeKey/SpikeTileKey` 解码出 `pre_global`

3. `SnnWorkload::expandPreGlobalToWindowEdgesFast_()`
   - 同文件
   - 查询 `lookupPostsLocalForPre_(pre_global)`
   - 立刻把一个 `pre_global` 展开成该 core 上全部 `post_local`
   - 对每个 `(post_local, pre_global, pre_rank)` 逐个写入 WMS

4. `WeightMemorySubsystem::beginApplyWindow()`
   - `services/synapse/weights/WeightMemorySubsystem.h`
   - `flipEdgesForApply()` 把收集好的 edge 从 `curr` 翻到 `prev`

5. `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()`
   - `services/synapse/weights/WeightMemorySubsystem.cc`
   - 再从 `(post_local, pre_global, pre_rank)` 恢复出 `addr`
   - 再按地址/line 去构建 issue queue

所以现在真实存在一段中间膨胀：

- **`token -> per-post edge materialization -> addr rebuild`**

这层膨胀在当前统计下，已经不是 DRAM line 粒度的瓶颈，但它仍然是接收侧对象数量、循环次数、哈希表写入量和调度入口膨胀的来源。

## 1.2 为什么当前不能直接做 PE-local HARBOR

当前一个很硬的结构约束是：

- `deliverPacket()` 是 **core-local 入口**
- 不是 `PE-local` 入口

证据就在：

- `components/MultiCorePE.cc`
- `cores_[endpoint_id]->deliverPacket(pkt);`

这意味着：

- 现在没有一个天然的、位于接收 PE 入口处的共享 token bridge
- 因而不能一步到位把 HARBOR 做成“完美的 PE-local 共享单元”

所以，具体落地必须分层：

- **先做 core-local 的 HARBOR-TAT-Core**
- 再做 PE-local 的 HARBOR-PE

## 1.3 本轮设计目标

本轮更具体的 HARBOR 方案，目标非常明确：

1. 不改变 GAS 严格语义
2. 不破坏当前 `GCSS-GLIDE` 的 row locality
3. 不引入新的跨 controller ownership 迁移
4. Phase A 先证明“token 共享语义延续到 memory service 入口”是可行且稳定的
5. Phase B 再把共享对象从 `core-local` 抬到 `PE-local`

---

## 2. Phase A：HARBOR-TAT-Core

## 2.1 目标

`HARBOR-TAT-Core` 是一个 **core-local token aggregation table**。

它不尝试改变当前 `dstcore` 物理存储口径，也不尝试绕开 WMS 的现有 retire/issue 逻辑；它只做一件事：

- **在 token 到达时只记 `pre_global -> arrival_count`，不立刻展开成 per-post edges**

等到 `BeginApply` 时，再一次性、按确定性顺序把这些聚合后的 `pre` 展开回 WMS。

因此 Phase A 的预期非常清晰：

- `memctrl.req_total` 基本不变
- `row_hit_rate_total` 基本不变
- `validation` 必须不变
- 但接收侧的对象膨胀、循环次数、edge 写入次数应明显下降

这一步的价值不在最终性能数字，而在于：

- 为后续 PE-local HARBOR 提供完全兼容的“中间表示”
- 给论文提供“共享语义没有必要在 receiver 入口立刻丢掉”的证据链

## 2.2 数据结构

在 `SnnWorkload` 中新增一组仅实验性启用的结构：

```cpp
struct HarborTatEntry {
    uint32_t arrival_count = 0;
    uint64_t first_touch_order = 0;
};

std::unordered_map<uint32_t, HarborTatEntry> harbor_tat_curr_;
std::vector<uint32_t> harbor_tat_touch_order_;
uint64_t harbor_tat_touch_seq_ = 0;
bool experimental_harbor_tat_core_enable_ = false;
```

约束：

- key 只用 `pre_global`
- value 只存：
  - `arrival_count`
  - `first_touch_order`

这里故意不存：

- `post_local`
- `edge list`
- `addr list`

因为这些都会把我们重新拉回旧的中间膨胀路径。

## 2.3 Gather / RX 路径

修改 `SnnWorkload::deliverPacket()` 与 `expandPreGlobalToWindowEdgesFast_()` 相关调用逻辑：

### 启用条件

只有在以下条件全部满足时才进入 `HARBOR-TAT-Core`：

- `experimental_harbor_tat_core_enable_ = 1`
- `workload_spike_input_enable_ = 1`
- `isWindowWorkload_() = true`
- `window_read_enable_ = true`
- `scheme1_enable_ = false`
- `synapse_weight_mode` 为当前主线 `premphf/plp` 系列
- `weight_mem_subsystem_ != nullptr`
- 当前包路径为 `fastpath`，而不是 `fallback/prism`

### 接收行为

对每个到达的 `pre_global`：

1. 更新 `harbor_tat_curr_[pre_global].arrival_count += 1`
2. 若首次出现，则记录 `first_touch_order`
3. 只保留 token 计数，不做 `lookupPostsLocalForPre_()`
4. 不调用 `recordEdgeWithPreRank()/recordEdgeWithWeight()`

这一步从根本上切断：

- token 到达时就立刻做 `pre -> posts_local` 展开

## 2.4 BeginApply 时的物化

推荐在 `SnnWorkload::clockTick()` 处理 `GasOp::BeginApply` 时，仿照当前 `PRISM` 的做法，在调用：

- `weight_mem_subsystem_->beginApplyWindow(...)`

之前新增：

- `materializeHarborTatToWeightSubsystem_()`

伪代码如下：

```cpp
void SnnWorkload::materializeHarborTatToWeightSubsystem_() {
    // 1. 按 first_touch_order 确定性导出 pre_global
    // 2. 对每个 pre 仅做一次 lookupPostsLocalForPre_(pre)
    // 3. 对其 posts_local[i] 调用:
    //    weight_mem_subsystem_->recordEdgeWithPreRankCount(
    //        post_local,
    //        pre_global,
    //        NaN,
    //        pre_rank = i,
    //        count = arrival_count);
    // 4. 导出完成后清空 harbor_tat_curr_
}
```

这里的语义关键点有两个：

1. **完全保留 multiplicity**
   - 以前若同一 `pre_global` 在同一窗口到达 `N` 次，会写入 `N` 轮相同 edge
   - 现在改成一次导出，但 `count = N`
   - 语义保持一致

2. **确定性不变**
   - 以 `first_touch_order` 固定导出顺序
   - 同一 `pre` 内仍按 `posts_local` 的升序导出 `pre_rank`
   - 不改变最终 `WMS retire` 的主链路数学含义

## 2.5 为什么 Phase A 不会改坏 GAS 语义

Phase A 只是在 gather 窗口内，把：

- 多次相同 `pre_global` 的重复 arrival

从“多次重复展开”为：

- “一次展开 + arrival_count”

最终落入 WMS 的仍然是：

- 同样的 `(post_local, pre_global, pre_rank, count)`

而当前主线已经存在：

- `recordEdgeWithPreRankCount(...)`

这说明：

- “按 count 聚合后再物化”并不是全新语义
- 它已经是当前代码认可的合法表示

因此，只要我们满足：

1. 不跨窗口合并
2. 不跨 `pre_global` 合并
3. 不丢失 `arrival_count`
4. 仍在 `BeginApply` 前完成物化

就不会改变当前严格 GAS 数学结果。

## 2.6 需要改动的文件

Phase A 仅涉及当前已有接收路径与统计链路，建议修改范围严格限定为：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.h`
  - 新增 `HarborTatEntry`
  - 新增 TAT 状态
  - 新增 `materializeHarborTatToWeightSubsystem_()`

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
  - `deliverPacket()`：改为 token-only 累积
  - `clockTick()/GasOp::BeginApply`：新增 TAT 物化调用
  - gather/scatter 边界：清理 TAT
  - stats 导出

- `sst_dram_si/mesh_template/build.py`
  - 注入新开关

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/SnnWorkloadStatsModule.h`
  - 添加统计 whitelist

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
  - 让新统计进入 `mesh_stats.csv`

Phase A **不需要**改：

- `WeightMemorySubsystem` 的主 issue/retire 机制
- `GCSS-GLIDE` 文件格式
- `MulticastRouter`

## 2.7 新增统计

Phase A 至少要补下列统计，才能形成论文可用证据链：

### 功能/规模类

- `gas_harbor_tat_rx_tokens_total`
  - TAT 收到的 token 总数

- `gas_harbor_tat_unique_pres_total`
  - 窗口内唯一 pre 总数

- `gas_harbor_tat_flush_pres_total`
  - BeginApply 时导出的 pre 数

- `gas_harbor_tat_flush_edges_total`
  - BeginApply 时实际物化出的 edge 数

- `gas_harbor_tat_arrival_count_total`
  - 所有导出 pre 的 arrival_count 求和

### 机理类

- `gas_harbor_tat_materialize_loops_saved_total`
  - 估算节省的 materialization 外层循环数
  - 公式建议：`sum_over_pre(arrival_count - 1) * posts_local_count`

- `gas_harbor_tat_token_dedup_ratio_avg`
  - `unique_pres / rx_tokens` 的窗口均值

- `gas_harbor_tat_lookup_posts_total`
  - 实际调用 `lookupPostsLocalForPre_()` 的次数

Phase A 的关键判据不是 `req_total`，而是：

- `lookupPostsLocalForPre_()` 次数大降
- `materialize_loops_saved_total` 明显 > 0
- `validation` 严格通过
- `req_total` / `row_hit_rate_total` 基本持平

## 2.8 闭环实验

实验承载目录建议：

- `mainexp/experiments/2026-03-11_harbor_tat_core_ab_v1/`

建议 case：

1. `full_system_baseline`
2. `full_system_baseline + harbor_oracle_only`
3. `full_system_baseline + harbor_tat_core`

建议至少跑两组口径：

### 口径 A：`step=1`

目的：

- 验证语义与主线一致
- 验证 `req_total` 不应明显变化
- 验证 `TAT` 统计链路完整

### 口径 B：`steps=2, seed-only`

目的：

- 让重复 pre 的可观测性更强
- 观察 `token_dedup_ratio` 与 `materialize_loops_saved_total`

Phase A 验收标准：

1. `validation.log`: `fail=0`
2. `memctrl.req_total` 变化应极小
3. `row_hit_rate_total` 无明显恶化
4. 新统计非 0，且能解释 receiver-side 膨胀被消掉

---

## 3. Phase B：HARBOR-PE

## 3.1 Phase B 的目标

如果说 Phase A 证明的是：

- “token 共享语义可以延续到 BeginApply 再物化”

那么 Phase B 要做的，是把共享层次再上提一级：

- **从 core-local 提升到 PE-local**

这一步才是第一个有机会进一步降低 `memctrl.req_total` 的阶段，因为它会改变：

- 存储组织粒度
- service 对象粒度
- 以及 DRAM 看到的真实请求对象

## 3.2 为什么必须引入新的 `dstpe` 口径

当前 `GCSS-GLIDE` 主线是：

- `dstcore` 物理组织

即便我们在接收侧把多个 core 的相同 `pre` 聚在一起，只要：

- values 仍然是按 core 分开的
- 地址空间仍是 per-core blob

那么 WMS 最终看到的仍会是：

- 多个 core 各自独立的 line 请求

这时共享 token 只能减少前端对象膨胀，不能实质减少后端 `req_total`。

因此，Phase B 必须配套一个新的 **PE-shared values 口径**：

- 建议实验名：`gcss_valueonly_dstpe_harbor_v1`

它的核心思想是：

- 同一 PE 内，按 `pre_global` 把多个 core 的 segment 编译进一个 PE-shared values blob
- 仍保留每个 core 的 descriptor
- 但让底层 line/row service 可以按 PE 聚合

## 3.3 Phase B 的硬件结构

推荐 HARBOR-PE 至少包含三个结构：

### 1. TAT-PE

key：

- `pre_global`

value：

- `arrival_count`
- `core_mask`
- `first_touch_order`
- `pending_service`

作用：

- 把来自同一接收 PE 的同一个 `pre` 合并成一个共享 token

### 2. PSD（PE-Shared Descriptor）

作用：

- 根据 `pre_global` 找到该 PE 内所有相关 core 的 segment descriptor

descriptor 内容建议包括：

- `core_id`
- `base`
- `len`
- `line_base`
- `line_span`

### 3. RWQ（Row Wave Queue）

作用：

- 把多个 core 的 descriptor 进一步合成为 line/row 粒度的 service wave
- 只生成 **PE-shared line request**
- 避免在 receiver 入口马上退化回 per-core edge flood

## 3.4 运行时流程

推荐 Phase B 运行时流程如下：

1. `SpikeKey/SpikeTileKey` 到达接收 PE
2. 不立刻按 endpoint 投喂 core-local fastpath
3. 先进入 `HARBOR-PE::acceptToken(pre_global, endpoint_id)`
4. `TAT-PE` 合并：
   - `arrival_count += 1`
   - `core_mask |= (1 << endpoint_id)`
5. 到 `BeginApply`：
   - 构建本窗口 immutable service plan
   - 查 `PSD`
   - 构建 `RWQ`
6. 按 PE-shared line 请求真实发射 DRAM 读
7. 返回后把对应 values attach 回各 core 的既有 GAS retire/accumulate 链路

这一步的关键不在“所有逻辑都共享”，而在：

- **line request 是共享的**
- **retire/accumulate 仍复用现有 per-core 语义主链**

## 3.5 Phase B 的接入位置

由于当前 `MultiCorePE` 直接按 `endpoint_id` 投给 core，所以 Phase B 推荐分两小步：

### Phase B1：PE-shared ingress table

不先改整个 packet ingress 所有权，而是在 `MultiCorePE` 内增加一个 PE-shared HARBOR 单元：

- core 收到 token 后，先把 `(endpoint_id, pre_global)` 上报到共享 HARBOR
- HARBOR 负责合并/计划
- Apply 前由各 core 向 HARBOR 请求本窗口的 service export

优点：

- 改动相对收敛
- 更容易和当前 `deliverPacket()` 主线兼容

### Phase B2：真正的 PE-local packet-first bridge

再把 `MultiCorePE::deliverPacketToEndpoint_()` 中对 spike packet 的处理前移到 HARBOR：

- `packet -> HARBOR-PE -> core callback`

这才是论文中更漂亮、也更像独立硬件单元的最终形态。

## 3.6 需要新增的离线格式

建议在 `sst_dram_si/tools/gcss/` 下新增一条实验性离线生成链路：

- `gen_gcss_valueonly_dstpe_harbor_v1.py`

输出建议：

- `peXX/gcss_dstpe_values.bin`
- `peXX/gcss_dstpe_idx.bin`
- `peXX/gcss_dstpe_meta.json`

`idx` 里至少包括：

- `pre -> pe_pre_id`
- `descriptor_offset`
- `descriptor_count`

descriptor 数组中再列出每个 core 的 segment：

- `core_id`
- `base`
- `len`

## 3.7 Phase B 的统计

Phase B 至少要新增这些统计，才能证明它真的改变了 memory service 对象：

- `gas_harbor_pe_rx_tokens_total`
- `gas_harbor_pe_unique_pres_total`
- `gas_harbor_pe_coremask_popcount_total`
- `gas_harbor_pe_descriptor_total`
- `gas_harbor_pe_shared_line_req_total`
- `gas_harbor_pe_line_fanout_total`
- `gas_harbor_pe_memctrl_req_elided_total`
- `gas_harbor_pe_attach_edges_total`

最关键的证据链应是：

1. `shared_line_req_total < attach_edges_total`
2. `memctrl.req_total` 下降
3. `row_hit_rate_total` 不恶化
4. `validation` 严格通过

## 3.8 闭环实验

实验承载目录建议：

- `mainexp/experiments/2026-03-11_harbor_pe_ab_v1/`

建议 case：

1. `full_system_baseline`
2. `full_system_baseline + harbor_tat_core`
3. `full_system_baseline + harbor_pe_dstpe_v1`

建议先做：

- `step=1` 冒烟
- `steps=2 seed-only` 正式 A/B

Phase B 验收标准：

1. `validation.log`: `fail=0`
2. `memctrl.req_total` 相对 baseline 可见下降
3. `row_hit_rate_total` 持平或更好
4. `sim_time_actual_ns` 至少方向正确
5. `shared_line_req_total` 与 `memctrl_req_elided_total` 非 0

---

## 4. 风险与护栏

## 4.1 语义护栏

无论 Phase A 还是 Phase B，都必须保持以下约束：

1. `orch_.acc_update(post_local, delta)` 的数学效果不变
2. 不引入跨 post 副作用
3. retire 仍保持当前严格 GAS 可验证链路
4. 所有实验性路径必须显式开关隔离

## 4.2 主线护栏

Phase A/B 都必须默认关闭，且只有：

- `MESH_EXPERIMENTAL_ENABLE=1`

时才允许开启。

建议新增：

- `MESH_HARBOR_TAT_CORE_ENABLE=1`
- `MESH_HARBOR_PE_ENABLE=1`

如果未满足主线权重模式、窗口模式、WMS ready 等条件，应自动回退到主线 baseline。

## 4.3 论文护栏

必须在文档和实验中明确区分：

- **Phase A：不会主打 `req_total` 收益**
- **Phase B：才是 memory x NoC 真正协同收益层**

否则很容易把“建立桥接表示”与“真正减少后端请求”混为一谈。

---

## 5. 建议的实际执行顺序

最稳妥的执行顺序如下：

1. 先落 `Phase A / HARBOR-TAT-Core`
   - 只改 `SnnWorkload + stats + build.py`
   - 做 `step=1` 和 `steps=2 seed-only`
   - 验证语义、统计、receiver-side 膨胀证据链

2. 在 Phase A 稳定后，再落 `Phase B1 / PE-shared ingress table`
   - 先不完全改 packet ownership
   - 先让共享单元存在，并能导出 PE-shared service plan

3. 最后再做 `Phase B2 / 真正 PE-local packet-first HARBOR`
   - 这是更完整、更有论文表现力的最终形态

---

## 6. 最终判断

结合当前代码结构、最新统计和已有失败经验，HARBOR 最合理的更具体落地方式，不是“一步到位的大一统硬件”，而是：

- **先用 `HARBOR-TAT-Core` 稳住表示层**
- **再用 `HARBOR-PE + dstpe` 真正改变 service 对象**

这样做的好处是：

1. 不会再掉进“改了很多，但统计全不变”的坑
2. 不会在还没有 bridge 表示层时就贸然改 PE-shared DRAM service
3. 能把“证明层”和“收益层”分开，实验解释力更强

因此，当前最值得立刻执行的下一步，不是继续在 WMS 内部硬抠 request，而是：

- **先落 Phase A，建立 HARBOR 的 core-local 可验证桥接层**
- **再把真正的收益目标留给 Phase B 的 `dstpe` 共享存储/共享 service**
