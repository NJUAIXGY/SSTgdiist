# 通用计算核“完成态”（packet-first + 可插拔 workload）验收口径

本文件定义 SnnDL 的“通用计算核完成态”目标与验收口径（DoD）。完成态的含义是：**平台核（CoreShell/NoC/Mem）只处理 time/packet/bytes/stat**，所有业务语义（SNN/Spike/GAS/BCSR/Step 或非 SNN stream）都以 workload/子系统方式加载，且能用 mesh 模板稳定回归。

> 注意：本文件只定义“完成态是什么/如何验收”，不再重复实现细节。目录与数据流总览见：`docs/SNNDL_HIERARCHY_AND_WORKFLOW.md`。

---

## 0) 关键约束

- **修改 C++ 必须 install 才生效**：
  - `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4 && make install`
- **禁止**依赖/开启：`use_event_weight_fallback=1`
- 回归入口脚本保持不变：`sst_dram_si/tools/run_mesh_with_time.sh`

---

## 1) Definition of Done（DoD）

当且仅当满足以下全部条件，视为“通用计算核完成态”达标：

### 1.1 架构边界（代码层可验证）

1) **平台面 packet-first**
   - NoC 输入统一为 `events/NocPacketEvent`；core 侧入口为 `deliverPacket()`（禁止主链路走 `deliverSpike()`）。
2) **NoC/Mem 语义隔离**
   - `services/noc/**` 不依赖 `SpikeEvent`（NoC 只处理 packet，不解析突触语义）。
   - `services/memory/**` 只承诺 `addr↔bytes`（不出现 weight/synapse/bcsr/route 字段）。
3) **workload 可插拔**
   - 通过参数 `workload_impl` 或环境变量 `SNNDL_WORKLOAD_IMPL` 在不改脚本的前提下切换 `snn/stream`。
4) **SNN 语义收敛到 workload**
   - CoreShell（`control/`）不再承载 SNN 业务状态机（GAS/window、weights、route/fanout、Step 注入等）。
5) **fail-fast**
   - 出现 `stdmem-untracked`、回包截断、歧义匹配等严重错误时直接 `fatal`，避免“静默归零”。

### 1.2 行为与回归（仿真可验证）

> 主人当前认可口径：10us 允许 `neurons_fired_total=0`；确定性允许轻微漂移（SNN），stream 要求严格一致。

1) **SNN（默认）100us 回归**
   - `cd "sst_dram_si" && export MESH_SIM_TIME="100us" && ./tools/run_mesh_with_time.sh`
   - 验收：`essential_summary_mesh.json` 中
     - `spike_activity.neurons_fired_total > 0`
     - `gas.gather_ns_p95/apply_ns_p95/scatter_ns_p95` 不允许三者全为 0
2) **SNN（默认）确定性（允许轻微漂移）**
   - 同 seed 运行两次 100us：
     - 用 `sst_dram_si/tools/compare_essential_summary_mesh.py` 对比（建议 `--rel-tol 0.01`，必要时放宽）
3) **Stream（新能力）100us 回归**
   - `cd "sst_dram_si" && export SNNDL_WORKLOAD_IMPL="stream" && export MESH_SIM_TIME="100us" && ./tools/run_mesh_with_time.sh`
   - 验收：`essential_summary_mesh.json` 中
     - `stream.stream_mem_verify_fail_total == 0`
     - `stream.stream_mem_bytes_written_total > 0` 且 `stream.stream_mem_bytes_read_total > 0`
     - `stream.stream_pkt_sent_total > 0` 且（2+ node 场景）`stream.stream_pkt_recv_total > 0`
4) **Stream（新能力）确定性（严格一致）**
   - 同 seed 运行两次 100us：
     - 用 `sst_dram_si/tools/compare_essential_summary_mesh.py --abs-tol 0 --rel-tol 0` 对比通过

---

## 2) 目录与边界索引（快速跳转）

- CoreShell：`control/README.md`
- 平台 NoC：`services/noc/README.md`
- 平台 Memory：`services/memory/README.md`
- Workload 插件：`services/workload/README.md`
  - SNN：`services/workload/snn/README.md`
  - Stream：`services/workload/stream/README.md`
- Synapse 语义域：`services/synapse/README.md`
- Stimulus：`services/stimulus/README.md`

