# PE Internal Band-Quality Owner-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `PE-internal gather-preband` 从“只有 line-level usefulness/resident-hit 计数”推进到“能回答 launched band 是否真的值得 future owner-first transaction”的 band-level realized quality probe，并以此为下一阶段 `owner-first metadata transaction before private issue` 提供数据闭环。

**Architecture:** 本阶段先不改 `private issue / exact retire` 主路径，也不继续在 `head2/tail prune` 上做局部参数博弈。推荐先增加一层严格隔离、默认关闭的 `band-level realized probe`：在 `preparePulseGatherPrebandReplay_()` 记录 launched band 的选中 line 集合，在 `endScatterWindow()` 基于 `PulseSeededLineTracker` 的 line state 回收并汇总 band 级 realized 质量，再把 raw/derived 指标导出到 `essential_summary_mesh.json`。当 probe 证明 multi-demand / multi-hit band 稀少时，再进入第二阶段的 `metadata overlap-strength` 与第三阶段的 `owner-first transaction` actual 机制。

**Tech Stack:** C++17, SST element `SnnDL`, `WeightMemorySubsystem`, `PulseSeededLineTracker`, `PulseGatherPrebandCollector`, seam tests, Python 3 summary pipeline, `unittest`, `mainexp` A/B experiment scripts.

---

## Current Conclusion

- 最新 fresh A/B 已经说明当前没进入收益空间的主因不是 `tail prune`，而是 launched useful line 的后续 resident reuse 深度太浅：
  - `pulse_mfb_gather_resident_hits_per_useful_line`
    - off: `1.0756302521008403`
    - on: `1.0890688259109311`
- 这意味着：
  - 多数 useful seeded line 只服务了大约一次后续 resident demand
  - 现在最缺的是 “band/object 级 realized quality” 数据，而不是更多 line-slot 局部调参
- 因此下一阶段的顺序必须是：
  1. `band-level realized quality probe`
  2. `metadata overlap-strength / consumer-strength probe`
  3. `owner-first metadata transaction before private issue`

## Design Choice

### Option A: 继续沿 line/head2/tail 桶细化

优点：
- 实现最小
- 延续现有 line tracker 与 summary 结构

缺点：
- 仍然回答不了 “哪个 band 值得被 future owner-first launch”
- 容易继续陷入只看 line-quality、不看 band reuse depth 的局部怪圈

### Option B: 先补 band-level realized quality probe

优点：
- 直接回答 launched band 的真实后效
- 为后续 owner-first 目标函数提供 ground truth
- 不改 actual service/commit contract，风险低

缺点：
- 需要在 `WMS` 多加一层窗口内 band bookkeeping
- 需要同步扩 summary test

### Recommended

采用 **Option B**，并按三阶段推进：

- `Phase-1`
  - realized probe only
  - 问题：哪些 launched bands 是 dead / single-useful / multi-useful / multi-hit
- `Phase-2`
  - 加 metadata overlap-strength probe
  - 问题：哪些 pre-launch 信号最能预测 Phase-1 的 realized 好 band
- `Phase-3`
  - 只把 strongest metadata object 推进为 `owner-first before private issue`

---

### Task 1: Define Phase-1 Band-Level Realized Probe Contract

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseSeededLineTracker.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/exp_opt/2026-03-24-pe-internal-optimization-loop-rootcause-and-next-stage.md`

**Step 1: Document the exact probe semantics**

定义 band-level raw counters：

- `pulse_mfb_gather_launched_bands_dead_total`
- `pulse_mfb_gather_launched_bands_single_useful_total`
- `pulse_mfb_gather_launched_bands_multi_useful_total`
- `pulse_mfb_gather_launched_bands_multi_resident_total`
- `pulse_mfb_gather_launched_bands_resident_hits_total`

定义 realized 规则：

- `dead`
  - band 内 `selected_line_addrs` 无任何 line 出现 `first_demand_seen`
- `single_useful`
  - 恰好 1 条 line 出现 `first_demand_seen`
- `multi_useful`
  - 至少 2 条 line 出现 `first_demand_seen`
- `multi_resident`
  - band 内 `resident_hit_total >= 2`

**Step 2: Add tracker query contract**

给 `PulseSeededLineTracker` 增加 line query API，用于窗口关闭前读取：

```cpp
struct LineStateSnapshot {
    bool valid = false;
    bool ready = false;
    bool first_demand_seen = false;
    uint64_t resident_hit_total = 0;
    uint8_t source_tag = 0;
    uint8_t aux_tag = 0;
};
```

**Step 3: Keep feature isolation explicit**

- probe 只在：
  - `pulse_mfb_gather_preband_enable == true`
  - `pulse_descriptor_actual_enable == true`
  - `window_seq != 0`
  下生效
- 没有新增 runtime behavior side-effect
- 没有改 existing owner/join/retire contract

**Done when:**
- Probe 语义写清楚
- 只读查询契约明确
- 不会误改 actual hot path

### Task 2: Write Failing Tests for Band-Level Realized Probe

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pe_internal_pod_shadow_wms_seam.cc`
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`

**Step 1: Add seam test for band-level realized categories**

新增最小 seam case，构造两个 launched bands：

- `band A`
  - 两条 launched line，均无后续 demand
  - 期望计入 `dead_total`
- `band B`
  - 两条 launched line，其中一条 single-useful，另一条多次 resident hit
  - 期望：
    - `single_useful_total == 1` 或 `multi_useful_total == 1`（按构造选择）
    - `multi_resident_total == 1`

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-seam-compile
```

Expected:
- FAIL，原因是新 band-level counters / query API 尚不存在

**Step 3: Add failing Python summary test**

在 `test_compute_essential_summary_mesh_pulse.py` 中新增 raw + derived 断言，至少覆盖：

- `pulse_mfb_gather_launched_bands_dead_total`
- `pulse_mfb_gather_launched_bands_single_useful_total`
- `pulse_mfb_gather_launched_bands_multi_useful_total`
- `pulse_mfb_gather_launched_bands_multi_resident_total`
- `pulse_mfb_gather_launched_bands_resident_hits_total`
- `pulse_mfb_gather_dead_band_ratio`
- `pulse_mfb_gather_multi_useful_band_ratio`
- `pulse_mfb_gather_multi_resident_band_ratio`
- `pulse_mfb_gather_resident_hits_per_launched_band`

**Step 4: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected:
- FAIL，原因是新的 pulse 字段与 derived 指标尚未导出

**Done when:**
- C++ seam test red
- Python summary test red

### Task 3: Implement Tracker Query and WMS Band Bookkeeping

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseSeededLineTracker.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

**Step 1: Add minimal query API**

在 `PulseSeededLineTracker` 增加：

- `queryLine(scope_id, window_seq, line_addr)`

返回 `LineStateSnapshot`，不修改已有 state。

**Step 2: Add launched-band window state**

在 `WeightMemorySubsystem` 增加窗口内 band record：

```cpp
struct PulseGatherLaunchedBandProbeEntry {
    uint64_t band_id = 0;
    uint32_t head_distance = 0;
    std::vector<uint64_t> selected_line_addrs;
};
```

记录时机：
- `preparePulseGatherPrebandReplay_()` 中 band 真正 `owner_launched` 时

**Step 3: Aggregate realized quality at window close**

在 `endScatterWindow()` 的 `PulseSeededLineTracker::closeWindow(...)` 前：

- 遍历 launched band entries
- 对每条 selected line 调 `queryLine(...)`
- 汇总 band 级：
  - useful line count
  - resident hit count
- 写入 raw counters

**Step 4: Keep resets/cleanup correct**

- reset diagnostics 时清空 band probe window state
- end-of-window housekeeping 时清空 band probe window state

**Step 5: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-seam-compile
cd "/home/xgy/remote" && python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected:
- PASS

**Done when:**
- 新 probe 完整接通且不改变既有 actual 行为

### Task 4: Export Derived Metrics Into Essential Summary

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`

**Step 1: Add derived ratios**

新增：

- `pulse_mfb_gather_dead_band_ratio`
- `pulse_mfb_gather_single_useful_band_ratio`
- `pulse_mfb_gather_multi_useful_band_ratio`
- `pulse_mfb_gather_multi_resident_band_ratio`
- `pulse_mfb_gather_resident_hits_per_launched_band`

**Step 2: Preserve compatibility**

- 若 denominator 为 0，不输出 derived 值
- 不改现有 line-level derived 指标

**Step 3: Run targeted tests**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected:
- PASS

### Task 5: Close the Loop With Targeted Build/Test and Mainexp

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`
- Run only: `/home/xgy/remote/mainexp/...`

**Step 1: Compile-check affected C++**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-seam-compile
```

**Step 2: Run probe-focused experiment**

在 `mainexp` 新开一轮 probe-only A/B：

- `gather_preband_probe_band_quality_off`
- `gather_preband_probe_band_quality_on`

要求：
- 其它已有 actual 机制保持一致
- 新 band-quality probe 仅增加统计，不改行为

**Step 3: Inspect whether multi-useful bands exist**

重点看：

- `pulse_mfb_gather_multi_useful_band_ratio`
- `pulse_mfb_gather_multi_resident_band_ratio`
- `pulse_mfb_gather_resident_hits_per_launched_band`
- 与已有：
  - `pulse_mfb_gather_resident_hits_per_useful_line`
  - `pulse_mfb_gather_ready_before_demand_ratio`

共同判断是否进入下一阶段：

- 若 `multi_useful_band_ratio` 很低：
  - 下一阶段转向 `metadata overlap-strength frontier`
- 若 `multi_useful_band_ratio` 不低但 `multi_resident_band_ratio` 仍低：
  - 下一阶段做 `owner-first metadata transaction`

**Step 4: Append TECH_PROGRESS.md**

只允许追加，至少记录：

- 修改文件
- 验证命令
- 新增 band-quality 指标
- 实验结论
- 下一阶段 TODO

**Done when:**
- 编译与 targeted tests 通过
- `mainexp` 有一轮 probe-only evidence
- `TECH_PROGRESS.md` 已追加

## Immediate Execution Choice

本会话直接按推荐路径执行：

1. 先落 `Task 2` 的 failing tests
2. 再做 `Task 3 + Task 4`
3. 最后做编译、自检与 `TECH_PROGRESS.md` 追加

不执行任何 git 写操作。
