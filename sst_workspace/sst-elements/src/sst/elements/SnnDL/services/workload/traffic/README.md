# services/workload/traffic/（Traffic Workload：通信/多播验证专用负载）

本目录存放 **TrafficWorkload**：一个“只做通信事务”的最小 workload，用于验证平台核的 NoC/packet-first 链路（尤其是 SpikeKey native multicast / blocked multicast）。

> 约束：该 workload 不建模神经动力学，不依赖 GAS/window，不依赖 memHierarchy/WeightLoader；它通过 `services/synapse/route` 复用 fanout/多播构建与发送事务。

## 默认内存语义（cacheline）

TrafficWorkload 主测 NoC/packet-first；若未来扩展到包含内存访问，其默认体系结构语义也必须遵循平台口径：**cacheline** 作为对外搬运与 `memHierarchy GetS/GetX` 统计对齐的基本单位。

---

## 主要文件

- `TrafficWorkload.{h,cc}`
  - 实现 `api/ICoreWorkload.h`
  - 周期性生成可复现的“本地 pre neuron 集合”，并通过 `SpikeCommSubsystem` 发射（可走 Spike 或 SpikeKey）
  - 接收网络包并做自检（尤其是 SpikeKey decode / stage / dst / mask 等检查）
  - 布局口径：复用 `services/workload/layout/NormalizedNeuronLayout`，确保 `neurons_per_pe`（per-PE）与 `global_neuron_base`（per-core）一致，避免投递错位

---

## 使用方式（典型）

### 选择 workload

- 组件参数：`workload_impl=traffic`
- 或环境变量：`SNNDL_WORKLOAD_IMPL=traffic`

### 关键参数（以实现为准）

- `traffic_enable`：是否启用发送
- `traffic_period_cycles`：发送周期（cycles）
- `traffic_batch_size`：每次发送的 pre 数量
- `traffic_seed`：采样随机种子（保证可复现）
- `traffic_pre_begin/traffic_pre_end`：采样的 pre 范围（**本 core 内的 neuron_idx**，范围 `[0, num_neurons)`；0 表示从头，end=0 表示到末尾）
- `traffic_stop_cycle`：到达该 cycle 后停止发送（0=不停止）
- `spikekey_check_enable/spikekey_check_fatal`：SpikeKey 自检开关与 fatal 策略

---

## 验收口径（建议）

当用于 native multicast 实验时，至少检查：

- `rx_spikekey_total > 0`（确实收到了 SpikeKey）
- `rx_spikekey_bad_total == 0`（mask/目的等检查无误）
- group-level 自检日志中无 `missing/dup/extra/meta_mismatch`（若启用 group 检查）
