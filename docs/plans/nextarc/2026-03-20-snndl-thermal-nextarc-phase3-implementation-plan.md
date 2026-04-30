# SnnDL Thermal Next-Arc Phase 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保持 `HotSpot offline-first` 主路径稳定的前提下，把现有热分析链路升级成“版本化 contract + 可回放窗口功率样本 + 只读热状态桥 + 正式 canonical sweep 套件”的第二阶段基础设施。

**Architecture:** 不再重复建设已经落地的 `window provenance v2 / memctrl / sweep report`，而是把当前离线链路里已经存在但尚未冻结的语义正式收敛成稳定接口。实现上分成四个代码任务和一个收尾任务：`Thermal Contract Freeze V2`、`WindowPowerSample Artifact`、`ThermalStateCache Replay Skeleton`、`Canonical Thermal Contract Suite`、以及统一验证与进展记录。

**Tech Stack:** Python 3、`unittest`、现有 `sst_dram_si/tools` 热分析脚本、`snn3dexp/thermal` 代理层、`tools/specs/mesh_hotspot_thermal_*.json`、append-only progress logging。

---

## Why This Plan

当前仓内真正已经落地的能力包括：

- `thermal_export.py` 已经有 `window_provenance`、`trace_source`、`window_scaling_mode`、`include_memctrl`、`grid_rows/grid_cols/grid_map_mode`、`layer_stack_validation`。
- `analyze_thermal_runs.py` 已经能导出 `temp_peak_over_ambient_c`、`temp_peak_over_avg_ratio`、`active_layer_count`、`layer_stack_validation_all_runs.csv`。
- `summarize_thermal_analysis.py -> export_thermal_sweep_report.py -> generate_thermal_sweep_report.py` 已经把 mixed 2D/3D sweep 做成统一 JSON + CSV/Markdown + 一键入口。

因此 phase 3 不应该继续把“能不能跑 HotSpot”当主线，而应该解决以下真正未完成的问题：

1. 当前输出合同虽已成形，但还没有版本化冻结，后续继续演进容易把上层消费方一起拉崩。
2. 当前 `window_provenance` 仍然是 run 级摘要，不是未来 runtime / replay / 近似热估计可直接消费的 `WindowPowerSample` 工件。
3. 在线 thermal feedback 设计文档已经存在，但代码里还没有最小 `ThermalStateCache` replay skeleton。
4. 当前热 smoke 与 mixed 报表虽然能跑，但还没有正式 canonical suite runner，仍偏向手工组合命令。

## Non-Goals

本计划明确不做：

- in-loop `HotSpot`
- runtime throttling / routing / mapping policy 接入
- `3D-ICE` 后端实现
- 完整 TSV / interposer / package 物理建模

### Task 1: Thermal Contract Freeze V2

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/summarize_thermal_analysis.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/export_thermal_sweep_report.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/generate_thermal_sweep_report.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_summarize_thermal_analysis.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_export_thermal_sweep_report.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_generate_thermal_sweep_report.py`

**Target contract additions:**

```json
{
  "thermal_contract_version": "v2",
  "analysis_contract_version": "v2",
  "sweep_summary_contract_version": "v2"
}
```

**Steps:**
1. 在 `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py` 写红灯测试，锁定 `thermal_summary.json` 顶层必须带 `thermal_contract_version="v2"`，并且已有 `trace_mode/window_count/window_source/window_provenance/layer_stack_validation` 不能回退或改名。
2. 运行定向测试：
   - `python3 -m unittest sst_dram_si.tools.test_thermal_export.ThermalExportCLITest -v`
   - 预期：因为缺少新 version 字段而失败。
3. 在 `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py` 写红灯测试，锁定 `thermal_analysis.json` 顶层必须带 `analysis_contract_version="v2"`，并保留 `provenance_summary/layer_stack_validation_summary/runs`。
4. 运行定向测试：
   - `python3 -m unittest sst_dram_si.tools.test_analyze_thermal_runs.AnalyzeThermalRunsCLITest -v`
   - 预期：因为缺少 version 字段而失败。
5. 在 `/home/xgy/remote/sst_dram_si/tools/test_summarize_thermal_analysis.py`、`/home/xgy/remote/sst_dram_si/tools/test_export_thermal_sweep_report.py`、`/home/xgy/remote/sst_dram_si/tools/test_generate_thermal_sweep_report.py` 写红灯测试，锁定 `thermal_sweep_overview.json` 与 wrapper stdout 里必须带 `sweep_summary_contract_version="v2"`。
6. 在 `/home/xgy/remote/sst_dram_si/tools/thermal_export.py` 中最小实现 version 字段，不改已有字段名，不重排现有 artifacts 语义。
7. 在 `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`、`/home/xgy/remote/sst_dram_si/tools/summarize_thermal_analysis.py` 中向上透传 version 字段，并保持 mixed/fallback 两条路径都一致。
8. 在 `/home/xgy/remote/sst_dram_si/tools/export_thermal_sweep_report.py` 与 `/home/xgy/remote/sst_dram_si/tools/generate_thermal_sweep_report.py` 中补齐 version 透传与 stdout 摘要字段。
9. 重新运行全部相关 thermal 工具测试，确认绿灯：
   - `python3 -m unittest sst_dram_si.tools.test_thermal_export sst_dram_si.tools.test_analyze_thermal_runs sst_dram_si.tools.test_summarize_thermal_analysis sst_dram_si.tools.test_export_thermal_sweep_report sst_dram_si.tools.test_generate_thermal_sweep_report -v`

### Task 2: WindowPowerSample Artifact

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/summarize_thermal_analysis.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_summarize_thermal_analysis.py`

**Target artifact:**

```json
{
  "sample_id": 1,
  "start_cycle": 0,
  "end_cycle": 999,
  "duration_ns": 1000,
  "trace_mode": "windowed",
  "blocks": [
    {
      "block_name": "tile_00_comp",
      "layer_name": "",
      "layer_index": null,
      "block_type": "comp",
      "power_w": 1.23e-06,
      "trace_source": "window_metrics",
      "window_scaling_mode": "per_tile_mean_normalized_metric",
      "cycle_model_applicable": true
    }
  ]
}
```

**Steps:**
1. 在 `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py` 写红灯测试，锁定 `thermal/summary/window_power_samples.jsonl` 在 average run 下至少导出 `1` 条 sample，在 windowed run 下按 `ptrace_row_count` 导出多条 sample。
2. 运行定向测试：
   - `python3 -m unittest sst_dram_si.tools.test_thermal_export.ThermalExportCLITest -v`
   - 预期：当前缺少 `window_power_samples.jsonl` artifact。
3. 在 `/home/xgy/remote/sst_dram_si/tools/thermal_export.py` 中新增最小导出函数，把现有 `ptrace_header/ptrace_rows/tile_summary_rows/window_ns/trace_source/window_scaling_mode` 重组为 `window_power_samples.jsonl`。
4. 在 `/home/xgy/remote/sst_dram_si/tools/thermal_export.py` 的 `thermal_summary.json["artifacts"]` 中登记：
   - `window_power_samples_jsonl`
5. 在 `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py` 中新增 run 级聚合字段：
   - `window_power_sample_count`
   - `window_power_block_count`
   - `window_power_trace_sources`
6. 在 `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py` 写红灯测试，锁定 mixed 2D/3D 聚合时这些字段可稳定导出到 `run_summary.csv` 与 `thermal_analysis.json`。
7. 在 `/home/xgy/remote/sst_dram_si/tools/summarize_thermal_analysis.py` 中向统一 JSON 透传：
   - `window_power_sample_count`
   - `window_power_trace_source_counts`
8. 重新运行相关测试，确认 green：
   - `python3 -m unittest sst_dram_si.tools.test_thermal_export sst_dram_si.tools.test_analyze_thermal_runs sst_dram_si.tools.test_summarize_thermal_analysis -v`
9. 用真实 mixed 目录复验：
   - `python3 /home/xgy/remote/sst_dram_si/tools/generate_thermal_sweep_report.py --analysis-dir /home/xgy/remote/tmp/hotspot_memctrl_mixed_analysis_v1`
   - 手工抽查：
     - `/home/xgy/remote/tmp/hotspot_memctrl_mixed_analysis_v1/thermal_sweep_overview.json`
     - `/home/xgy/remote/tmp/hotspot_memctrl_3d_smoke_v1/20260320-105412/thermal/summary/window_power_samples.jsonl`

### Task 3: ThermalStateCache Replay Skeleton

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/state_cache.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_thermal_state_cache.py`
- Optional integration test: `/home/xgy/remote/snn3dexp/tests/test_thermal_proxy.py`

**Target interfaces:**

```text
ThermalStateCache
  sample_id
  source
  layers[]
  blocks[]

BlockTemperatureState
  block_name
  temperature_c
  valid
  source
```

**Steps:**
1. 新建 `/home/xgy/remote/snn3dexp/tests/test_thermal_state_cache.py`，写红灯测试，锁定可以从：
   - `thermal_summary.json`
   - `tile_temperature_summary.csv`
   - 可选 `window_power_samples.jsonl`
   构建一个只读的 `offline_hotspot_replay` cache。
2. 运行定向测试：
   - `python3 -m unittest snn3dexp.tests.test_thermal_state_cache -v`
   - 预期：当前模块不存在而失败。
3. 在 `/home/xgy/remote/snn3dexp/thermal/state_cache.py` 中实现最小 loader：
   - `load_offline_hotspot_state(...)`
   - `get_block_temperature(...)`
   - `get_layer_temperature(...)`
   - 不接任何 runtime side effect。
4. 在 `/home/xgy/remote/snn3dexp/thermal/__init__.py` 中导出该接口，避免外部模块直接依赖内部路径。
5. 在 `/home/xgy/remote/snn3dexp/tests/test_thermal_proxy.py` 增加一个轻量集成测试，确认 `build_thermal_summary(...)` 的现有 proxy 输出不会被新 state cache 改坏。
6. 运行回归：
   - `python3 -m unittest snn3dexp.tests.test_thermal_state_cache snn3dexp.tests.test_thermal_proxy -v`

### Task 4: Canonical Thermal Contract Suite

**Files:**
- Create: `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_contract_suite_v1.json`
- Create: `/home/xgy/remote/sst_dram_si/tools/run_thermal_contract_suite.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_run_thermal_contract_suite.py`
- Reference existing specs:
  - `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_smoke_v3.json`
  - `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_smoke_v3.json`
  - `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_csv_smoke_v1.json`
  - `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_stats_prefix_smoke_v1.json`
  - `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_power_source_smoke_v1.json`

**Suite intent:**

- `2D block`
- `3D grid`
- `csv power source`
- `stats_prefix power source`
- `memctrl on/off`
- `average/windowed`

**Steps:**
1. 新建 `/home/xgy/remote/sst_dram_si/tools/test_run_thermal_contract_suite.py`，写红灯测试，锁定 suite runner 能读取 manifest、为每个 case 生成 run/report 命令、并输出统一结果清单。
2. 运行定向测试：
   - `python3 -m unittest sst_dram_si.tools.test_run_thermal_contract_suite -v`
   - 预期：runner 与 manifest 不存在而失败。
3. 新建 `/home/xgy/remote/tools/specs/mesh_hotspot_thermal_contract_suite_v1.json`，明确 canonical case 列表、spec path、是否要求 `window_power_samples`、是否要求 `layer_stack_validation`。
4. 新建 `/home/xgy/remote/sst_dram_si/tools/run_thermal_contract_suite.py`，最小实现：
   - 读取 manifest
   - 对每个 case 生成 `run_mesh_with_time.sh` 命令
   - 对每个 run 自动调用 `generate_thermal_sweep_report.py`
   - 输出统一 JSON manifest/result
5. 先不要做并发执行、也不要做 fancy dashboard，只要求可复跑、可落盘、可留证据。
6. 运行工具测试变绿：
   - `python3 -m unittest sst_dram_si.tools.test_run_thermal_contract_suite -v`
7. 选择至少一个小套件 smoke 复验：
   - `python3 /home/xgy/remote/sst_dram_si/tools/run_thermal_contract_suite.py --manifest /home/xgy/remote/tools/specs/mesh_hotspot_thermal_contract_suite_v1.json --out-dir /home/xgy/remote/tmp/thermal_contract_suite_v1`

### Task 5: Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Steps:**
1. 跑 `sst_dram_si/tools` 相关完整 thermal 回归：
   - `python3 -m unittest sst_dram_si.tools.test_thermal_export sst_dram_si.tools.test_analyze_thermal_runs sst_dram_si.tools.test_summarize_thermal_analysis sst_dram_si.tools.test_export_thermal_sweep_report sst_dram_si.tools.test_generate_thermal_sweep_report sst_dram_si.tools.test_run_thermal_contract_suite -v`
2. 跑 `snn3dexp` 热状态桥相关回归：
   - `python3 -m unittest snn3dexp.tests.test_thermal_state_cache snn3dexp.tests.test_thermal_proxy -v`
3. 运行真实 mixed 目录的一键报表与最小 suite smoke，确认：
   - `thermal_sweep_overview.json`
   - `thermal_sweep_report.csv`
   - `thermal_sweep_report.md`
   - `window_power_samples.jsonl`
   均真实存在。
4. 只在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾 append：
   - 新增 contract version
   - 新增 `WindowPowerSample` artifact
   - 新增 replay-only `ThermalStateCache`
   - 新增 canonical suite runner
5. 最后手工核对：
   - mixed 目录和旧式 3D fallback 目录都仍可导出
   - 没有破坏 `layer_stack_validation_all_runs.csv` fallback 语义
   - 没有把 runtime policy 行为混入本轮实现

## Exit Criteria

本计划完成时，应满足：

1. `thermal_summary.json`、`thermal_analysis.json`、`thermal_sweep_overview.json` 都带清晰 version 字段。
2. 每个 thermal run 都可以产出机器可消费的 `window_power_samples.jsonl`。
3. `snn3dexp` 中存在一个 replay-only `ThermalStateCache`，可读离线 HotSpot 结果，但不接行为控制。
4. 仓内存在一套正式的 canonical thermal contract suite，可重复复验 2D/3D/memctrl/power source 组合。
5. 所有进展均已追加记录到 `TECH_PROGRESS.md` 文件尾部。
