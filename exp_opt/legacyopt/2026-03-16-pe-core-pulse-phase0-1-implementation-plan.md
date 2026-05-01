# PULSE-GDR Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` when implementing this plan task-by-task.

**Goal:** 将当前 `shared ingress actual path v1` 收敛为一条真正能够在现有主线上产生收益的 `PULSE-GDR` 落地路线：先修正统计与对象边界，再把 `PULSE` 从 `packet-first ingress sharing` 推进到 `gather-bounded descriptor-first shared service`，最后再以强隔离方式引入 `domain-local exact retire`。

**Architecture:** `MultiCorePE` 保持为 `PE` 级运行时宿主；`PeSharedCoreFabric` 从 ingress mirror 提升为 `Gather-Harbor + Descriptor Lifter + Shared Region Agenda + Retire scoreboard host`。第一阶段不碰 retire 行为，只建立 observe-only descriptor path；第二阶段引入 actual shared descriptor service；第三阶段才引入 `shadow` 与 `actual` 两阶段 `retire domains`。

**Tech Stack:** C++17、SST Element、轻量单测（`g++` + `assert`）、`make test-compile`、fresh `mainexp` A/B。

---

## Scope Freeze

本计划只做以下事情：

- 修正 `PULSE v1` 当前误导性的计数口径，明确 shared participation 的真实比例；
- 引入 `Gather-Harbor` 和 `Descriptor Lifter`，让 `PE` 在 gather 边界上显式看见 `packet -> descriptor` 压缩；
- 把 shared path 的真实对象从 packet 改成 descriptor/service；
- 在默认关闭、强隔离前提下，增加 `shadow retire domains` 与 `actual retire domains` 开关；
- 所有 fresh 实验继续放在 `mainexp`。

本计划明确不做：

- 不推翻当前 `GCSS-GLIDE + STORM + MulticastRouter` 主线；
- 不把 `weight_idx/value` 一步到位改成全局共享 cache；
- 不在没有 `shadow` 验证前直接替换 retire contract；
- 不改 baseline 默认行为；
- 不做任何 git 写操作。

---

## Task 1: 修正 v1 统计口径，建立真实 benefit baseline

**Why first:** 当前 `pulse_ingress_core_dispatch_total` 会把“真实 shared dispatch”和“bypass 后 direct deliver 的记账”混在一起；如果不先拆口径，后续所有设计实验都无法判断到底有没有真实共享收益。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `sst_dram_si/tools/compute_essential_summary_mesh.py`
- Test: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pe_shared_core_fabric.cc`

**Required new counters:**
- `pulse_ingress_shared_buffered_total`
- `pulse_ingress_shared_dispatch_total`
- `pulse_ingress_direct_deliver_total`
- `pulse_ingress_singleton_bypass_total`
- `pulse_ingress_deadline_bypass_total`
- `pulse_ingress_pressure_bypass_total`
- `pulse_ingress_actual_participation_ratio`（summary 侧导出）

**Success criteria:**
- 能区分：
  - 真正进入 ingress buffer 的包
  - 真正通过 shared batch drain 投递的包
  - 因 singleton/deadline/pressure 回退的包
- `essential_summary_mesh.json["pulse"]` 中可直接读出这些指标

**Verification:**
- `g++` fabric 单测通过
- `python3 -m unittest "sst_dram_si.tools.test_compute_essential_summary_mesh_pulse"` 通过

---

## Task 2: 引入 Gather-Harbor observe-only，对象从 packet 改成 gather bucket

**Why:** fresh 数据已经说明：
- `packets_during_gather_total = 1,206,784`
- `packets_during_apply_total = 0`
- `gather_ns_avg` 远小于 `apply_ns_avg`

因此 gather 是 descriptor formation 的天然边界。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Test: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pe_shared_core_fabric.cc`

**Required runtime objects:**
- `GatherHarborBucket`
- key:
  - `step_id`
  - `post_block_id`
  - `weight_region_id`
  - `retire_domain_id`
- fields:
  - `packet_count`
  - `consumer_count`
  - `consumer_bitmap`
  - `first_arrival_cycle`
  - `last_arrival_cycle`

**Behavior (observe-only):**
- 只在 gather 窗口内对 eligible activation 建 bucket
- 不改最终 packet ownership
- gather close 时导出 bucket 统计，不改行为

**Required new counters:**
- `pulse_harbor_buckets_total`
- `pulse_harbor_packet_sum`
- `pulse_harbor_consumer_sum`
- `pulse_harbor_bucket_peak`
- `pulse_harbor_singleton_buckets_total`

**Success criteria:**
- 能在 fresh run 上证明：
  - bucket 化后平均 `packets_per_bucket > 1`
  - singleton share 是否足够低，值得进入 descriptor-first 路线

---

## Task 3: 引入 Descriptor Lifter observe-only，测量 packet-to-descriptor 压缩

**Why:** 当前 real run 已经显示：
- `spike_packets_total / apply_completed_granules_total ≈ 8`

但我们还没有在 `PE` 内把这种压缩显式建模出来。

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PulseDescriptor.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.cc`
- Create/Test: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_descriptor_lift.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`

**Descriptor fields:**
- `step_id`
- `window_id`
- `post_block_id`
- `weight_region_id`
- `retire_domain_id`
- `consumer_bitmap`
- `consumer_count`
- `packet_count`
- `slack_to_apply_close`
- `region_safe`

**Lift rule v1:**
- same `step`
- same `post_block`
- same `weight_region`
- `consumer_count >= 2` or `packet_count >= P_min`
- 不跨 retire domain

**Required new counters:**
- `pulse_descriptor_total`
- `pulse_descriptor_packet_sum`
- `pulse_descriptor_consumer_sum`
- `pulse_packets_per_descriptor_avg`
- `pulse_descriptor_singleton_drop_total`

**Success criteria:**
- fresh run 上能直接量化 descriptor 压缩倍数
- 能回答“值得共享的对象占比是多少”

---

## Task 4: 落地 actual shared descriptor service，不再只共享 ingress

**Why:** 这是第一步真正可能带来收益的 actual path。  
shared path 必须开始共享：
- `weight region / granule service`
- refill 后的 ready fanout

而不是只共享 packet admission。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Minimum actual behavior:**
- descriptor 进入 `Shared Region Agenda`
- agenda 以 `weight_region/granule` 为服务对象，而不是 per-packet/per-core 立即 issue
- service 完成后 fanout 到多个 consumer
- architectural retire 行为仍保持旧逻辑

**Required new counters:**
- `pulse_shared_service_hits_total`
- `pulse_shared_service_misses_total`
- `pulse_region_service_entries_peak`
- `pulse_region_service_replay_total`
- `pulse_ready_fanout_total`
- `pulse_ready_fanout_avg`

**Success criteria:**
- fresh A/B 中至少一个主线指标出现正向变化：
  - `memory_requests`
  - `memctrl.req_total`
  - `apply_first_down_resp_delay_ns_avg`
  - `apply_ns_avg`
- 若无变化，则必须能证明 descriptor actual participation 仍过低，并给出下一轮收敛方向

---

## Task 5: 引入 shadow retire domains，先测理论收益上界

**Why:** 当前最大 stall 来自 `cross-post HOL`。  
在没有 `shadow` 的情况下直接改 retire 风险太高。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`

**Shadow-only behavior:**
- 维持真实 `global_inorder retire`
- 并行维护一个 `retire_domain shadow scoreboard`
- 统计如果按 domain-local retire，会释放多少 blocked cycles / blocked edges

**Required new counters:**
- `pulse_retire_domain_shadow_hol_cycles_total`
- `pulse_retire_domain_shadow_blocked_edges_total`
- `pulse_retire_domain_active_peak`
- `pulse_retire_domain_committable_edges_peak`

**Success criteria:**
- shadow 结果能证明 domain-local retire 确实释放显著 HOL
- 且该收益大于引入 shared descriptor service 的 correctness overhead

---

## Task 6: 落地 actual domain-local exact retire

**Why:** 这是 `PULSE-GDR` 最核心的一刀，也是理论上最可能带来显著收益的一刀。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Test: add or extend focused retire-domain tests

**Contract:**
- same-post deterministic
- exactly-once
- drain-before-scatter
- `service_complete != retire_visible`

**Minimum actual domain key:**
- `retire_domain_id = post_block_id`

**Required new counters:**
- `pulse_retire_domain_commit_total`
- `pulse_retire_domain_hol_cycles_total`
- `pulse_retire_global_head_blocked_cycles_total`
- `pulse_retire_ready_not_visible_cycles_total`

**Success criteria:**
- fresh A/B 中：
  - `retire_wait_cycles_due_to_hol_total` 显著下降
  - `sim_time_actual_ns` 相对 baseline 出现清晰正收益
- correctness validation 仍为：
  - `fail=0 warn=0 strict=0`

---

## Task 7: mainexp 实验矩阵与论文口径快照

**Why:** `PULSE-GDR` 不是一个单 case feature，必须拆清收益来源。

**Experiment matrix:**
1. baseline
2. `shared ingress actual v1`
3. `harbor + descriptor lift observe-only`
4. `descriptor actual service + global retire`
5. `descriptor actual service + shadow retire domains`
6. `descriptor actual service + actual retire domains`

**Artifacts:**
- 每组单独目录放在 `mainexp/experiments/...`
- 每组统一导出：
  - `essential_summary_mesh.json`
  - `validation.log`
  - `snapshot/compare.tsv`

**Must-have derived metrics:**
- `packets_per_descriptor_avg`
- `descriptor_consumer_fanout_avg`
- `shared_service_hit_ratio`
- `retire_domain_shadow_gain_ratio`
- `correctness_overhead_per_gain`

---

## Verification Matrix

- C++ focused unit tests
  - `test_pe_shared_core_fabric.cc`
  - `test_pulse_descriptor_lift.cc`
- compile check
  - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`
- install
  - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j1 && make install`
- runtime config checks
  - `python3 -m unittest "sst_dram_si.mesh_template.test_runtime_pulse_config"`
- summary checks
  - `python3 -m unittest "sst_dram_si.tools.test_compute_essential_summary_mesh_pulse"`
- fresh experiment checks
  - `validation: fail=0 warn=0 strict=0`

---

## Notes

- `v1` 的最大价值不是性能，而是证明：
  - shared path 可以真实接管 activation 数据面
  - baseline 能保持完全隔离
- `v2/v3` 的首要目标不是“更多共享”，而是“共享真正能减少工作量的对象”
- 如果 `Task 3` 发现 `packets_per_descriptor_avg` 没有显著大于 1，则必须暂停，不要盲目推进 actual descriptor service
- 如果 `Task 5` 发现 `shadow retire domains` 收益很小，也必须暂停，不要贸然改 retire contract
