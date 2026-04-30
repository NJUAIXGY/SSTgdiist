# SnnDL Thermal Next-Arc Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把当前 `HotSpot offline-first` 热链路从“可正式产出”推进到“语义更强、3D 校验更深、批量分析更适合 sweep、并为在线反馈保留稳定接口”的下一阶段基础设施。

**Architecture:** 继续保持 `offline-first` 主路径不变，只在 `mesh_template -> effective_config -> thermal_export.py -> analyze_thermal_runs.py` 这条数据链上做增量增强。实现上分成四个代码任务和一个设计任务：窗口级 provenance v2、stack validation v2、analysis v2、最小 memctrl 热块，以及在线 thermal feedback 接口设计文档。

**Tech Stack:** Python 3、`unittest`、现有 `mesh_template` 配置链、`thermal_export.py`、`analyze_thermal_runs.py`、append-only progress logging。

---

### Task 1: Window Provenance V2

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`

**Steps:**
1. 写红灯测试，锁定 `thermal_summary.json` 与 `tile_temperature_summary.csv` 中的新 provenance 字段。
2. 运行定向测试，确认当前缺字段或语义不满足而失败。
3. 在 `thermal_export.py` 中补充：
   - run 级 `window_provenance`
   - layer/block 级 `trace_mode`、`trace_source`、`window_scaling_mode`
   - 对 `window_metrics` / `csv` / `none` / average fallback 的显式区分
4. 再跑定向测试，确认变绿。

### Task 2: Layer Stack Validation V2

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Steps:**
1. 写红灯测试，锁定更强的 `layer_stack_validation` 明细与批量导出字段。
2. 运行定向测试，确认当前失败。
3. 在 `thermal_export.py` 中补：
   - `grid_rows/grid_cols/grid_map_mode`
   - package / sink / spreader / interface 关键参数快照
   - failure 明细里带 `expected_floorplan_file` / `lcf_floorplan_file`
4. 在 `analyze_thermal_runs.py` 中把这些信息导出到 run/layer/fail-layer 视图。
5. 重新跑测试确认通过。

### Task 3: Analysis V2 For Sweeps

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Steps:**
1. 写红灯测试，锁定新的 sweep 友好派生指标。
2. 运行测试验证红灯。
3. 在 `run_summary.csv` / `layer_summary.csv` / `thermal_analysis.json` 中补：
   - `peak_over_avg`
   - `peak_over_ambient`
   - `layer_power_share`
   - `active_layer_count`
   - provenance 汇总字段
4. 再跑测试确认通过。

### Task 4: Minimal Memctrl Thermal Block

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/spec.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/legacy_defaults.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_spec_resolver.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_thermal_config.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Steps:**
1. 先写红灯测试，锁定 `thermal.include_memctrl` 与 `mesh_memctrl_east` 的合同。
2. 跑测试确认当前确实失败。
3. 增量实现：
   - spec/runtime/build 透传 `include_memctrl`
   - `thermal_export.py` 增加 east-edge memctrl strip
   - 为 memctrl 选择最小可解释功耗代理
   - summary / analysis 识别 `block_type=memctrl`
4. 再跑测试确认通过。

### Task 5: Online Thermal Feedback Interface Design

**Files:**
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-online-thermal-feedback-interface-design.md`

**Steps:**
1. 基于前四项落地后的接口，写一份在线温度反馈接口设计文档。
2. 文档明确：
   - `window power sample` 合同
   - thermal state cache
   - runtime consumer hooks
   - 与当前 offline artifacts 的兼容关系
   - 为什么当前不直接做 in-loop HotSpot

### Task 6: Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Steps:**
1. 跑热分析定向回归。
2. 跑 `mesh_template + thermal tools` 联合回归。
3. 追加 `TECH_PROGRESS.md`，只在文件末尾 append。
4. 最后核对新文档与新 CSV/JSON 字段是否已落盘。
