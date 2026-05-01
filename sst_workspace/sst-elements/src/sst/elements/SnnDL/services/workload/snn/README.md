# services/workload/snn/（SNN Workload：Spike/GAS/BCSR/Step 主链路）

本目录存放 **SNN 工作负载的主链路实现**：输入队列、GAS window 推进、权重读取与累加、fanout/route/通信，以及与 compute core 的交互都在此处闭环完成。

> 目标：CoreShell（`control/`）只做 time/packet/stat；SNN 的业务状态机全部下沉到 workload 插件，避免语义上浮。

## 默认内存语义（cacheline）与结果解读

- 平台默认的体系结构语义为 **cacheline 粒度**（对齐 `memHierarchy GetS/GetX`）。
- SNN workload 的 GAS/BCSR 路径可能形成大于 cacheline 的合并读（overfetch）；在分析结果时，必须同时查看：
  - `memctrl.bytes_est_total = requests_received_GetS * line_size_bytes`（off-chip traffic 主口径）
  - `gas_unique_bytes_total/gas_unique_reads_total`（GAS 合并覆盖口径；dense microbench 默认应接近 cacheline）
  - `effective_config.json`（记录 effective 的 merge_policy/line_size/granularity，防止配置文件与实际行为漂移）

---

## 主要文件

- `SnnWorkload.{h,cc}`
  - 负责 `ICoreWorkload` 的实现：`configureFromParams/onClockTick/deliverPacket/getStatistics`
  - 在内部装配并驱动：
    - `services/synapse/weights`（权重与窗口读编排）
    - `services/synapse/route`（fanout 与 Spike 通信事务）
    - `services/synapse/gas`（edge/accumulator 辅助结构）
    - `services/stimulus`（Step 注入与外部输入注入，若启用）
    - `compute/*`（`ISnnComputeCore`：动力学/学习/输出事件）

---

## neuron layout 口径（P0：错位会直接导致路由/投递错误）

`SnnWorkload` 在 `bindRuntime()` 时会对布局做归一化与 fail-fast 校验（实现见 `services/workload/layout/NormalizedNeuronLayout`）：

- `num_neurons`：每 core 的 neuron 行数（`neurons_per_core`）
- `neurons_per_pe`：每 PE 的 neuron 总数（`cores_per_pe * neurons_per_core`）
- `global_neuron_base`：本 core 的 global base（用于 `source_global = base + neuron_idx`）

## 输入/输出边界

- 输入：
  - 来自 NoC 的 `NocPacketEvent(kind=Spike)`（由 `SpikePacketBridge` 解码为 Spike 语义并递送到 workload）
  - 来自 Stimulus 的本地注入（走 `INocTransport::injectLocal`，仍以 packet-first 进入）
- 输出：
  - 输出 fire events → `services/synapse/route/SpikeCommSubsystem` fanout → packet → `INocTransport::sendFromCore`

---

## 与其他域的关系（简图）

```
CoreShell (control) ── onClockTick/deliverPacket ─▶ SnnWorkload
SnnWorkload ─▶ compute(ISnnComputeCore)
SnnWorkload ─▶ synapse(weights/route/gas)
SnnWorkload ─▶ stimulus(step/external) ─▶ noc(INocTransport)
```

---

## 验证建议（与 mesh 模板一致）

- 100us 回归入口：`sst_dram_si/tools/run_mesh_with_time.sh`
- 关键摘要：`essential_summary_mesh.json`（由 `sst_dram_si/tools/compute_essential_summary_mesh.py` 聚合）
