# Experiments（统计落盘）

本子目录提供“运行 + 解析日志 + 落盘统计”的最小工具链，避免依赖 SST 统计注册时序限制。

## 输出文件（每个 case）

- `sst.log`：原始 SST 输出（便于复盘）
- `routers.csv`：逐 router 计数（来自 `[mcast-router]`）
- `cores.csv`：逐 core 计数（来自 `[traffic]`）
- `noc_lat.csv`：逐 node 的 NoC 端到端延迟画像（来自 `[noc-lat]`）
- `summary.json`：汇总指标 + 配置快照 + 校验结果

## 推荐入口

```bash
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" --seeds 1 2 3 --sim-time "20us"
```

脚本会在 `experimental_features/native_multicast_lab/experiments/runs/` 下创建时间戳目录，并生成 suite 级汇总。
