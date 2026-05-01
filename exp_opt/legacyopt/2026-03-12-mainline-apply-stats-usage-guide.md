# 主线 Apply 统计使用指南（最小可观测性）

> 日期：2026-03-12  
> 适用范围：`DRAM-based SNN + STORM + GAS + GCSS-GLIDE + MulticastRouter` 主线  
> 目标：不盲动优化，先用统一统计快速判断瓶颈在 `ready / issue / response / retire`

---

## 1. 你会得到哪些统计文件

一次正常主线运行后，重点看这两个文件：

1. `pe*/pe_step_perf_db.csv`
- 每个 step 的原始账本（最细的稳定口径）。
- 新增 Apply 关键字段都在这里。

2. `essential_summary_mesh.json`
- 离线聚合后的总览（跨 PE、跨 step）。
- `gas.*` 给 totals/ratio/avg delay；`step.per_step[*]` 保留逐步明细。

---

## 2. Apply 新字段说明（按链路分组）

### 2.1 Issue 侧
- `apply_issue_attempt_total`：Apply 期发射尝试次数。
- `apply_issue_success_total`：发射成功次数（至少发出一个 fragment）。

### 2.2 Block reason 侧
- `apply_issue_block_no_ready_total`：当前周期没有可发 granule。
- `apply_issue_block_inflight_cap_total`：被 inflight 上限卡住。
- `apply_issue_block_retire_guard_total`：窗口收尾/退役保护导致不能结束。

### 2.3 Ready 队列侧
- `apply_ready_queue_peak`：Apply 窗口内可发队列峰值。
- `apply_ready_queue_nonempty_cycles_total`：可发队列非空周期数。

### 2.4 响应里程碑（相对 BeginApply）
- `apply_first_issue_delay_ns`
- `apply_first_down_resp_delay_ns`
- `apply_first_granule_done_delay_ns`
- `apply_first_up_resp_delay_ns`

### 2.5 进度总量
- `apply_down_resp_total`
- `apply_completed_granules_total`
- `apply_emitted_subreads_total`

---

## 3. summary 中可直接使用的派生指标

`essential_summary_mesh.json -> gas` 中新增：

- `apply_issue_success_ratio`
- `apply_issue_block_inflight_cap_ratio`
- `apply_issue_block_retire_guard_ratio`
- `apply_ready_queue_nonempty_ratio`
- `apply_first_*_delay_ns_avg`
- `apply_subreads_per_completed_granule_avg`

`step.per_step[*]` 中新增逐步派生：

- `apply_issue_success_ratio`
- `apply_issue_block_inflight_cap_ratio`
- `apply_issue_block_retire_guard_ratio`
- `apply_ready_queue_nonempty_ratio`

---

## 4. 快速诊断规则（先观测，后优化）

1. `no_ready` 高：
- 常见含义：前端供给不足（RX/构段/ready 形成慢）。

2. `inflight_cap` 高：
- 常见含义：内存返回慢或并发上限偏紧，Issue 端被反压。

3. `retire_guard` 高：
- 常见含义：response 已有进展，但窗口收尾/step closure 被卡。

4. 里程碑延迟判读：
- `first_issue` 高：进入 Apply 后很久才开始发。
- `first_down_resp` 高：发得出但 memory 首包慢。
- `first_granule_done` 高：碎片回包慢/尾部慢。
- `first_up_resp` 高：下游完成后上游发放仍慢。

---

## 5. 推荐使用流程（每轮 A/B 固定执行）

1. 运行主线并产出 run 目录。
2. 重新计算 summary：
```bash
python3 sst_dram_si/tools/compute_essential_summary_mesh.py --run-dir <RUN_DIR>
```
3. 优先看：
- `gas.apply_issue_*`
- `gas.apply_first_*_delay_ns_*`
- `step.per_step[*]` 中最慢 step 的上述同名字段。
4. 再决定下一轮只改一个旋钮（避免多变量混叠）。

---

## 6. 注意事项

- 老 run 没有 `pe_step_perf_db.csv` 新列时，这些指标可能为 0 或缺失，不代表“没有瓶颈”。
- 统计语义以主线 runtime 为准，不要与已废弃旁路优化字段混合解读。
- 先看 ratio，再看 total；先看 step 慢点，再看全局均值。

