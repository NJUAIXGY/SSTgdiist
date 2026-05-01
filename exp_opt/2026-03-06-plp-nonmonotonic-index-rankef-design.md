# PLP 非单调 `slot_base` 压缩索引设计（Rank+EF）

作者：浮浮酱（nekomata-engineer）  
日期：2026-03-06  
适用范围：`gcss_valueonly_dstcore_vlf_premphf_plp` 及后续所有“physical_pre_order != slot_order”的 exact layout 方案

---

## 1. 问题定义

当前 PLP 的收益已经成立，但主线合入仍被一个核心问题卡住：

- `PLP` 会按 `physical_pre_order` 重排不同 pre 段在 values 里的物理顺序；
- 运行时 lookup 仍必须保持 `lookup(pre) -> (base, len)`；
- 现有主线 `PreMPHF(v2, EF-base)` 只支持 **slot 顺序下单调的 `slot_base`**；
- 一旦 `physical_pre_order` 与 MPHF `slot_order` 脱钩，`slot_base[slot]` 在 slot 维度上就变成非单调；
- 结果是 PLP 目前只能退回 `v1 slot arrays`，索引成本从主线的 `~0.0655 values` 回升到 `~0.4719 values`。

本设计要解决的问题是：

**在不改变 runtime lookup 语义、不改变 GAS 语义、不引入 membership check 的前提下，把“非单调 slot_base”重新压回到接近主线 v2 的索引成本。**

目标：

- 继续保持 exact 语义：`(pre_global, post_local) -> weight` 完全不变；
- 运行时接口保持 `lookup(pre)->(base,len)`；
- 索引重新回到 `index << values`，理想目标仍是 `index_to_values_ratio <= 0.1`；
- 方案必须适用于任意 `physical_pre_order`，而不仅是 PLP 当前的 `profile_greedy`。

---

## 2. 当前实现为什么失败：代码级根因

### 2.1 v2 EF-base 只编码“单调 base 序列”

主线 generator 在 [`gen_gcss_valueonly_dstcore_vlf_premphf.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py#L411) 的 `_build_ef_from_slot_base()` 里，明确要求：

- `bases = slot_base + [edges_total]`
- 对每个 `i>0` 检查 `bases[i] >= bases[i-1]`
- 否则直接抛出 `non-monotonic base sequence`

也就是说，v2 的 Elias-Fano 不是“压任意 base 数组”，而是只压 **非降序 base 前缀数组**。

### 2.2 runtime loader 也把“单调性”当成格式不变量

在 [`GcssIndexPreMphf.h`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h#L442) 的 `validateV2EliasFano_()` 里，runtime 会对每个 `i in [0, pre_count]` 解出 `efBaseAt_(i)`，并强制要求：

- `base[0] == 0`
- `base[i] >= base[i-1]`
- `base[last] == edges_total`
- `base[i+1] > base[i]`

如果不满足，直接报：

- `ef_base_not_monotonic`
- `ef_zero_or_negative_len`
- `ef_last_base_mismatch_edges_total`

### 2.3 lookup 路径本质上假设“len = next_base - base”

在 [`GcssIndexPreMphf.h`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h#L175) 的 `lookup()` 里：

- v1 路径：直接读 `slot_base_[slot]` + `slot_len_[slot]`
- v2 路径：读 `efBaseAt_(slot)` 和 `efBaseAt_(slot+1)`，用 `next-base` 得到 `len`

这意味着 v2 本质上编码的是“**slot 顺序下的 prefix partition**”，而不是一般的 `(slot -> base, len)` 映射。

### 2.4 PLP 为什么天然破坏这一点

主线 premphf generator 在 [`gen_gcss_valueonly_dstcore_vlf_premphf.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py#L315) 中按 `slot_keys` 顺序写 values：

- `slot_base[slot] = len(values)`
- 再把该 slot 对应 pre 的权重顺序 append 到 values

所以这里的 `slot_base` 天然单调。

而 PLP generator 在 [`gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py#L240) 中先按 `physical_pre_order` 写 values，再回填：

- `base_by_pre[pre] = len(values)`
- `slot_base[slot] = base_by_pre[slot_keys[slot]]`

因此 `slot_base` 不再按 `slot` 单调，只是一个“slot -> 某个物理 prefix 起点”的任意置换结果。

这也是当前 PLP 文件头直接写在源码注释里的现实约束：[`gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py#L18)

- “Arbitrary PLP reordering makes `slot_base[slot]` non-monotonic in MPHF slot order”
- “the current EF-based v2 index format is not valid here”

结论：

**问题不是 Elias-Fano 不够强，而是我们把“压缩对象”选错了。**

---

## 3. 关键观察：非单调的不是 prefix，本质是“slot 到 physical rank 的置换”

定义：

- `slot(pre)`：MPHF 给 pre 分配的逻辑槽位
- `rank(pre)`：该 pre 在 `physical_pre_order` 中的物理顺序号，范围 `[0, pre_count)`
- `base_by_rank[r]`：按 `physical_pre_order` 做 prefix sum 后，第 `r` 个 pre 段的起始 base

则真实 lookup 可以写成：

1. `slot = MPHf(pre)`
2. `rank = rank_of_slot[slot]`
3. `base = base_by_rank[rank]`
4. `next = base_by_rank[rank+1]`
5. `len = next - base`

这里有一个非常关键的结构分解：

- `rank_of_slot[slot]` 是**任意置换**，不单调；
- `base_by_rank[r]` 是**严格单调 prefix 数组**；
- `len` 仍然可以由相邻 prefix 差分得到，无需单独存 `slot_len`。

因此，只要我们把“任意置换”和“单调 prefix”拆开压缩，就能恢复主线 v2 那种压缩思路。

这也是本方案的核心：

**不要再压 `slot_base[slot]`，改为压 `slot->rank` + `rank->base_prefix`。**

---

## 4. 方案比较

### 4.1 方案 A：Rank+EF（推荐）

结构：

- `slot -> rank`：定宽 bitpack 或块化 bitpack
- `rank -> base_prefix`：Elias-Fano
- `len = prefix[rank+1] - prefix[rank]`

优点：

- 完全 exact
- lookup 接口保持不变
- 只在 loader 内部增加一层 rank 解码
- 单调部分仍由 EF 承担，复用现有代码最多
- 大小上很有希望重新压到 `values/10` 以下

缺点：

- runtime lookup 比 v2 多一步 `slot -> rank` 解码
- 需要在格式层新增 version / extra header

### 4.2 方案 B：Block-Min + Delta（不推荐作为主方案）

结构：

- 把 slot 分块
- 每块存 `min_base`
- 每个 slot 存 `base-min` 的 bitpack delta
- `len` 单独压缩

优点：

- 实现简单

缺点：

- 对“任意置换”并不稳健；PLP 的 `slot_base` 跨块振荡时 delta 范围可能很大
- 仍需单独存 `len`
- 压缩上限受数据分布影响大，缺少普适性

### 4.3 方案 C：直接压置换（Lehmer / ANS / wavelet 等）（保留为远期）

结构：

- 使用更接近排列熵的 codec 去压 `slot->rank` 置换
- `rank->base_prefix` 仍走 EF

优点：

- 理论上比定宽 rank 更省

缺点：

- runtime 硬件实现复杂
- 代码改动大
- 不适合当前主线合入目标

**结论：主线推荐方案是 A：Rank+EF。**

---

## 5. 推荐方案：PLP-Index v3 = Rank+EF

### 5.1 数据格式

建议保持 magic 不变：`GCSSVLFP`，新增 `version = 3`。

Header 思路：

```c
struct HeaderV3Extra {
  uint32_t rank_bits;
  uint32_t rank_word_count;
  uint32_t ef_l;
  uint32_t ef_low_word_count;
  uint32_t ef_high_word_count;
  uint32_t ef_select_step;
  uint32_t ef_select_count;
};
```

文件体顺序建议：

1. `rank_words[]`：bitpacked `rank_of_slot[slot]`
2. `ef_low_words[]`
3. `ef_high_words[]`
4. `ef_select_samples[]`
5. `pilots[]`

其中：

- `rank_of_slot` 长度 = `pre_count`
- `base_by_rank` 长度 = `pre_count + 1`
  - 最后一个元素固定为 `edges_total`

### 5.2 runtime lookup

lookup 流程变成：

1. `bucket = hash1(pre, seed) % bucket_count`
2. `pilot = pilots[bucket]`
3. `slot = slotPos(pre, seed, pilot, pre_count)`
4. `rank = rankAt(slot)`
5. `base = efBaseAt(rank)`
6. `next = efBaseAt(rank+1)`
7. `len = next - base`

返回值仍是：

- `out_base = base`
- `out_len = len`

因此 [`WeightMemorySubsystem::lookupGcssPreBaseLen_()`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc#L1389) 完全不需要改接口。

### 5.3 为什么这能重新兼容 EF

因为现在进入 EF 的不再是“slot 顺序下的 base”，而是：

- `base_by_rank[0] = 0`
- `base_by_rank[r+1] = base_by_rank[r] + len(physical_pre_order[r])`

这条序列天然严格单调，完全满足当前 `validateV2EliasFano_()` 所要求的数学性质。

换句话说：

- **非单调性被局限在 `slot->rank` 这一层**
- **EF 继续只负责单调 prefix 层**

这正是最符合现有 runtime 结构的分工。

---

## 6. 大小估算

以 `4x4 bcsr10k step1` 的数量级估算：

- `pre_count ≈ 10k`
- `edges_total ≈ 128k`
- `rank_bits = ceil(log2(pre_count)) = 14`

则：

### 6.1 `slot->rank`

- `10k * 14 bits ≈ 140k bits ≈ 17.1 KiB`

### 6.2 `rank->base_prefix (EF)`

`n = pre_count + 1 ≈ 10k`

按 `U/n ≈ 12.8`，则 `l ≈ 3`：

- low bits：`~10k * 3 bits ≈ 3.7 KiB`
- high bits：`~((U>>l)+n) bits ≈ (16k+10k) bits ≈ 3.2 KiB`
- select hints：通常 `<1 KiB`

合计约：`~7-8 KiB`

### 6.3 pilots

- `bucket_target = 4` 时，约 `pre_count/4` 个 pilot
- `~2500 B ≈ 2.4 KiB`

### 6.4 总计

- `rank + EF + pilots ≈ 27-28 KiB/core`

相对 `values ≈ 500 KiB/core`：

- `index_to_values_ratio ≈ 0.05-0.06`

这已经回到主线 v2 量级，甚至在一些规模下可能更优。

注意：

- 这个估算还没有利用块级 rank 压缩；
- 若未来发现 `rank` 在 profile-guided 布局下具备局部性，还可以继续做 block-local remap；
- 但即便只做定宽 bitpack，第一阶段也已经足够有主线价值。

---

## 7. 为什么它不改变语义

本方案只是把同一个映射拆成两层：

- 旧：`slot -> (base, len)`
- 新：`slot -> rank -> (base, len)`

只要离线生成保证：

- `rank_of_slot[slot(pre)] = physical rank of pre`
- `base_by_rank` 正确对应同一 `physical_pre_order`

那么运行时得到的 `widx = base + pre_rank` 与当前 PLP v1 完全一致。

因此不会改变：

- `(pre_global, post_local) -> weight`
- `pre_rank` 语义
- GAS retire / apply 顺序
- validation 结果

这仍然是 exact layout transformation，不是近似压缩。

---

## 8. 代码落点

### 8.1 生成器侧

核心文件：

- [`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py)
- [`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py`](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py)

建议改法：

1. 在 PLP generator 中构造：
   - `physical_pre_order`
   - `rank_by_pre`
   - `rank_of_slot[slot] = rank_by_pre[slot_keys[slot]]`
   - `base_by_rank`（按 physical order 前缀）
2. 复用现有 EF builder，但压的对象改成 `base_by_rank[:-1]`
3. 新增 `version=3` 写盘逻辑
4. meta/manifest 里记录：
   - `index_format = rankef_v3`
   - `rank_bits`
   - `rank_words_bytes`
   - `ef_bytes`
   - `pilots_bytes`

### 8.2 runtime loader

核心文件：

- [`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h)

建议改法：

1. 新增 `version == 3` 分支
2. 新增 `HeaderV3Extra`
3. 新增成员：
   - `rank_words_`
   - `rank_bits_`
4. 新增 helper：
   - `rankAt_(slot, out_rank)`
5. 新增校验：
   - `rank_bits` 足够表示 `[0, pre_count)`
   - 每个 `rank < pre_count`
   - `rank_of_slot` 为全排列（可选：离线强校验 + runtime 轻校验）
   - `base_by_rank` 的 EF 仍严格单调，最后值等于 `edges_total`
6. `lookup()` 新增 `IndexLayout::RankEf`

### 8.3 runtime SRAM 统计

文件：

- [`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc#L1389)

建议：

- 当前 idx-sram 记账还是按 legacy `slot_base/slot_len` 路径写的；
- v3 时应改成：
  - seed
  - bucket_count
  - pilot
  - rank word(s)
  - EF low/high/select 触发的读取模型

这不影响语义，但会影响论文里 SRAM 访问统计的真实性。

---

## 9. 验证计划

### 9.1 结构自检

离线生成器必须自检：

- 对每个 pre：
  - `slot = mphf(pre)`
  - `rank = rank_of_slot[slot]`
  - `base = base_by_rank[rank]`
  - `len = base_by_rank[rank+1]-base_by_rank[rank]`
  - 按 `pre_rank` 回取所有 values，必须与原 PLP v1 完全一致

### 9.2 runtime 语义验证

A/B/C：

1. `plp_v1_arrays`
2. `plp_v3_rankef`
3. baseline `gcss_valueonly_dstcore_vlf_premphf`

验收：

- `plp_v1_arrays` 与 `plp_v3_rankef`
  - `validation.log` 均 `fail=0 strict=0`
  - 关键 memory / GAS / SNN 统计一致或仅有实现无关噪声
- `plp_v3_rankef` 相对 `plp_v1_arrays`
  - 性能不应退化明显
  - `synapse.index_cost.index_to_values_ratio` 明显下降

### 9.3 关键统计

建议补到 summary：

- `synapse.index_cost.rank_words_bytes`
- `synapse.index_cost.ef_bytes`
- `synapse.index_cost.pilots_bytes`
- `synapse.index_cost.index_total_bytes`
- `synapse.index_cost.index_to_values_ratio`
- `synapse.index_cost.index_bits_per_edge`

这样后面可以直接证明：

- PLP 的收益来自 value-plane
- 而 Rank+EF 修复的是 index-plane
- 两者可以组合成一条主线方案，而不是互相排斥

---

## 10. 风险与边界

### 10.1 最大风险

`slot->rank` 虽然只是 bitpack，但它是一次额外随机访存；若 SRAM 访问模型过于保守，可能在统计上放大 lookup 成本。

但这条风险是可接受的，因为：

- 当前 v1 arrays 本来就在读 `slot_base + slot_len`
- `rank+EF` 读的总字节数通常不会更大
- 论文主指标里更重要的是 `index size` 与 `payload utilization` 的组合

### 10.2 不建议第一阶段做的事

- 不要一开始就上复杂 permutation codec
- 不要试图把 `rank` 和 `pilot` 联合熵编码
- 不要改 runtime API
- 不要把 PLP 和新的 issue/retire 机制混在一起实现

先把 `Rank+EF` 做成一个结构清晰、证据硬的 exact index 修复方案，再谈第二阶段进一步压缩。

---

## 11. 结论

推荐主线设计：

**PLP Index v3 = `slot->rank` bitpack + `rank->base_prefix` Elias-Fano + pilots**

原因：

1. 它准确抓住了“非单调 slot_base”的真正来源是 permutation，而不是 prefix 本身。
2. 它保持 `lookup(pre)->(base,len)` 不变，runtime 侵入最小。
3. 它把任意 `physical_pre_order` 的问题转化成“压 permutation + 压单调 prefix”，结构上普适。
4. 在当前规模下，尺寸上有很大把握回到 `index_to_values_ratio <= 0.1`。
5. 它能把当前已经证明有效的 `PLP value-plane` 路线，从“实验性 v1 arrays”推进到“主线可合入索引体系”。

---

## 12. 下一步实现建议

1. 先在 PLP generator 上做 `version=3 rank+ef` 原型，不改现有 v1 路径。
2. 在 `GcssIndexPreMphf.h` 增加 `version=3` loader 与 `lookup()` 分支。
3. 先做离线自检 + 小规模 runtime 严格验证。
4. 再进入 `memop` 闭环，对比：
   - `plp_v1_arrays`
   - `plp_v3_rankef`
   - baseline `v2(EF-base)`
5. 若索引比例回到 `<=0.1` 且性能不退化，则可把 `PLP + Rank+EF` 作为下一条 memory 主线候选。
