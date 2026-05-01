# snndl-thing-exp

`snndl-thing-exp/` 是一个**顶层独立实验容器**，专门用于承载 `SnnDL SRAM timing` 相关 smoke / debug / ablation 测试。

## 设计目标

- 不向 `mainexp/`、`memop/`、`sst_workloads/` 写入新的实验 case 或输出目录
- 不要求修改 `sst_dram_si/local_run_config.json`
- 用 `spec-first` 驱动 mesh，并把所有运行产物限制在 `snndl-thing-exp/` 自己目录下

## 目录结构

- `cases/<case_id>/case.json`：case 元信息与默认环境变量
- `cases/<case_id>/spec.json`：spec-first 配置
- `tools/run_case.py`：统一 runner
- `tests/`：runner 自测
- `runs/`：真实 mesh run 输出
- `run_logs/`：额外日志目录预留
- `snapshot/`、`summary/`：后续分析产物预留

## 当前 case

- `sram_timing_smoke`
  - 目的：验证 SRAM timing 第一阶段的独立实验容器能跑通
  - 特征：`max_steps=1`、`drain-based step completion`、`step random activation (fraction=0.001, fanout=1)`、打开 `state/weight SRAM`
- `state_sram_debug`
  - 目的：关闭 `weight_idx/weight_l0` 模型，只观察 `state SRAM` 访问与 stall
- `weight_idx_sram_debug`
  - 目的：切到 `gcss_valueonly_dstcore_idx2` 且关闭 ingress prefetch，只观察 `weight_idx` SRAM
- `weight_l0_fill_smoke`
  - 目的：打开 idx2 ingress prefetch，稳定触发 `weight_l0` lookup/fill
- `sram_mixed_smoke`
  - 目的：同时覆盖 `state + weight_idx + weight_l0`，作为 mixed SRAM smoke

## 用法

先校验 spec：

```bash
cd "/home/xgy/remote"
python3 "snndl-thing-exp/tools/run_case.py" sram_timing_smoke --validate-only
```

查看 dry-run：

```bash
cd "/home/xgy/remote"
python3 "snndl-thing-exp/tools/run_case.py" sram_timing_smoke --dry-run
```

正式运行：

```bash
cd "/home/xgy/remote"
python3 "snndl-thing-exp/tools/run_case.py" sram_timing_smoke
```

所有输出默认都会落到：

- `snndl-thing-exp/runs/sram_timing_smoke/<timestamp>/`
