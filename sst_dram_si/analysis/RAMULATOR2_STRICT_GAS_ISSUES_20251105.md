# Ramulator2 在严格 GAS 场景下的读响应缺失问题（2025-11-05）

本文档汇总近期在单 PE 严格 GAS（window_auto=1，200/40/40ns）场景下，Ramulator2 后端出现“读响应缺失 / granule 长时间 NOT ready”的问题、现象对比、可能原因与验证计划。作为当前问题跟踪与复现实验指南使用。

## 1) 场景与现象
- 规模：单 PE，20 核 × 50 神经元/核 = 1000；数据集：3% × fanout 256，ts=5us。
- 严格 GAS：Gather/Apply/Scatter 固定窗口（200/40/40ns），Apply 统一回答、Scatter 统一 ΔV+发放。
- 权重：内存权重，WeightLoader 在 run 时以 fill=1.0 写入；核心按窗发起列读补 cache。

现象对比（同一套上层逻辑）：
- simpleMem（baseline）
  - 读请求与 ReadResp 正常，`memory_requests≈1.3K`，`dram_bytes_read≈5.2MB`；358 个窗口稳定推进；出现非零发放。
- ramulator2（DDR4 openrow）
  - 多次在 1k@100us 下出现：GBI `issueGranuleBuf_` 触发，但 `ReadResp` 不回（或极少回），窗口内 granule 长时间 NOT ready，最终统计口径为 “读请求=0 / 发放=0”。
  - 小规模 4×10 曾在早期版本出现成功样例，但近期复测更稳定的是 simpleMem；ramulator2 在 20×50 场景仍表现为响应缺失。

## 2) 已排除与无效尝试
- L1 cache 干预：
  - coherence_protocol 改为 `none` → 无效。
  - 绕过 L1、GBI 直连 bus → 无效。
- GBI 粒度清空 bug：
  - 已修复 emitApplyResponsesBuf_ 仅清 ready granule、保留未完成项（避免 pending 丢失）。问题仍在。
- Bank 映射：
  - 之前的 `RandomTranslation` 已改为 openrow 配置，且脚本显式传入 `bank_bits=4/bank_shift=16`，避免 bank×row 推断失效。

## 3) 可能原因（待验证）
1. 高并发 inflight 限制触发：`max_inflight_reads=256` 在 20×50 场景下不足，导致后续请求被 gating 或下游 stall。
2. 双缓冲/窗口切换搅动：Apply/Gather 交替与 defer/merge 路径组合下，窗口边界出现长期等待（尤其 Apply 窗短，仅 40ns）。
3. ramulator2 后端在严格窗口模式下的时序/节奏不匹配：大量小粒度/合并粒度请求在短窗内倾倒，返回节奏错过 Apply 回答期，使上游长期“NOT ready”。

## 4) 建议的 A/B 验证矩阵（ramulator2 专用）
在 `sst_dram_si/local_run_config.json` 调整以下参数，每次仅改一项，记录 `gas_reads_issued / memory_requests / dram_bytes_read / EndScatter.spikes_emitted`：

- 并发与窗口：
  - A1: `gas_max_inflight_reads=1024`（从 256 提升）
  - A2: `gas_window_cycles_apply=200`（从 40 提升至 200ns）
  - A3: `window_read_budget=64`（从 512 降低，防止一窗爆量）
  - A4: 组合：A1+A2+A3（强节流+放宽 Apply 回答时间）

- 合并与 defer：
  - B1: `defer_issue_until_apply=1` + gap_merge（现状）
  - B2: `defer_issue_until_apply=0`（立即下发 granule），其余不变

- 规模：
  - C1: 4×10，5us（小规模对照组）
  - C2: 10×20，20us（中规模）
  - C3: 20×50，100us（目标规模）

记录口径（均来自 CSV 与 summary）：
- GBI：`gas_reads_issued`（SnnDL.GatherBufferIF，门控下发计数）
- PE：`memory_requests`、`mem_req_size_bytes`（直方图 Sum.u64）
- DRAM：ramulator2 日志 `total_num_read_requests`（若可用）
- 发放：`EndScatter.spikes_emitted` 总和；`pe_window_spikes_db.csv`

## 5) 复现与基线
- simpleMem 基线（已验证）：
  - 1k@100us：`memory_requests≈1301`、`dram_bytes_read≈5.2MB`、358 个窗口稳定；`total_neurons_fired>0`。
  - 运行：
    ```bash
    bash sst_dram_si/tools/run_singlepe_with_time.sh
    # summary: sst_dram_si/outputs_large/paper2/dram_N1k/essential_summary.json
    ```

- ramulator2 待测模板：
  - 改回：`mem_backend=ramulator2`，`ramulator2_config_file=snt_dram_si/configs/ramulator2_ddr4_openrow.cfg`
  - 逐项执行 4.中的 A/B/C 项，采集上述口径。

## 6) 结论与下一步
- 结论：问题更像是“严格 GAS 窗口 + 高并发 + 合并策略 + ramulator2 时序”组合导致的返回节拍不匹配；simpleMem 基线说明上层链路无功能性错误。
- 下一步：按 A/B 矩阵窄化参数空间，锁定最小可用解（优先 A1+A2+A3）。若仍无法稳定，则考虑在 GBI 增加“Apply 尾部 tail-wait（有限超时）”或“窗口后沿容忍回答”的可选策略（仅 ramulator2 路径下启用），以避免窗口切换瞬间的回答丢失。

---

附：参考路径
- GBI 修复：`SnnDL/GatherBufferIF.cc` `emitApplyResponsesBuf_()` 保留未完成 granule、仅清 ready 项。
- 窗口读注入：`SnnPESubComponent.cc` `BeginApply` 分支（`window_read_enable`/`window_read_budget`）。
- 汇总器：`sst_dram_si/tools/compute_essential_summary_singlepe.py`（支持 wallclock、窗口分布与 sanity 均值校验）。
