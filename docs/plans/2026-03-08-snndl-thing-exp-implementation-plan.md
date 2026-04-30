# snndl-thing-exp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 搭建独立的 `snndl-thing-exp/` 实验容器，用 spec-first + isolated run root 承载 SnnDL SRAM timing 测试。

**Architecture:** 顶层独立目录，使用 `cases/<case_id>/{case.json,spec.json}` 描述实验，`tools/run_case.py` 统一解析 case、验证 spec、设置 `MESH_RUN_ROOT` 并调用现有 mesh runner。所有输出都限制在 `snndl-thing-exp/` 下。

**Tech Stack:** Python 3、JSON、SST mesh runner、`unittest`

---

### Task 1: 写 runner 测试

**Files:**
- Create: `snndl-thing-exp/tests/test_run_case.py`
- Test: `snndl-thing-exp/tests/test_run_case.py`

**Step 1: Write the failing test**
- 覆盖 `resolve_case_context()`：
  - spec 路径必须位于 `snndl-thing-exp/cases/<case_id>/spec.json`
  - `MESH_RUN_ROOT` 必须位于 `snndl-thing-exp/runs/<case_id>`
  - 默认 env 里包含 `MESH_VALIDATE_PROFILE=dev`

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snndl-thing-exp/tests/test_run_case.py`
- Expected: FAIL，提示 `run_case.py` / `resolve_case_context` 不存在。

**Step 3: Write minimal implementation**
- 新建 `snndl-thing-exp/tools/run_case.py`
- 实现 case 加载、路径解析、dry-run 输出。

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest snndl-thing-exp/tests/test_run_case.py`
- Expected: PASS

### Task 2: 搭实验骨架

**Files:**
- Create: `snndl-thing-exp/README.md`
- Create: `snndl-thing-exp/.gitignore`
- Create: `snndl-thing-exp/cases/sram_timing_smoke/case.json`
- Create: `snndl-thing-exp/cases/sram_timing_smoke/spec.json`
- Create: `snndl-thing-exp/runs/.gitkeep`
- Create: `snndl-thing-exp/run_logs/.gitkeep`
- Create: `snndl-thing-exp/snapshot/.gitkeep`
- Create: `snndl-thing-exp/summary/.gitkeep`

**Step 1: Write minimal files**
- README 说明隔离原则与运行方式
- `.gitignore` 忽略运行产物
- `case.json` 给出默认 env
- `spec.json` 提供 SRAM smoke 配置

**Step 2: Validate spec**
- Run: `python3 sst_dram_si/tools/mesh_spec_cli.py validate snndl-thing-exp/cases/sram_timing_smoke/spec.json`
- Expected: `OK`

### Task 3: 验证 runner

**Files:**
- Modify: `snndl-thing-exp/tools/run_case.py`

**Step 1: Add dry-run / validate-only**
- 支持 `--dry-run` 打印 command + env
- 支持 `--validate-only` 只做 spec 校验

**Step 2: Verify command generation**
- Run: `python3 snndl-thing-exp/tools/run_case.py sram_timing_smoke --dry-run`
- Expected: 输出 `MESH_RUN_ROOT=.../snndl-thing-exp/runs/sram_timing_smoke`

### Task 4: 进展记录

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Append update**
- 记录新增实验容器、运行方式、隔离边界、验证命令
