# services/workload/stream/（Stream Workload：packet-first 通信 + 内存校验）

本目录存放 **完全非 SNN 的 streaming 工作负载**：通过 NoC 发送/接收自定义 packet，并对内存做 read-after-write 校验（用于验证平台核的 NoC/Mem/packet-first 闭环）。

> 约束：该 workload 不依赖 `SpikeEvent`、不依赖 `services/synapse/*`、不依赖 `services/stimulus/*`。

## 默认内存语义（cacheline）

StreamWorkload 的目标是验证“平台核”的通用能力，因此其内存行为默认遵循平台的体系结构口径：**cacheline 粒度**作为对外搬运与 `memHierarchy GetS/GetX` 统计对齐的基本单位。
若进行 row-streaming/DMA 等更强假设的实验，应使用其他 workload/配置，并在输出中显式标注，避免混入通用核验收结论。

---

## 主要文件

- `StreamWorkload.{h,cc}`
  - 实现 `ICoreWorkload`：按固定节奏生成 packet、发起内存写入/读回，并对读回 bytes 做校验。
  - 统计（写入 `mesh_stats.csv` 并汇总到 `essential_summary_mesh.json`）：
    - `stream_mem_writes_issued_total / stream_mem_reads_issued_total`
    - `stream_mem_bytes_written_total / stream_mem_bytes_read_total`
    - `stream_mem_verify_pass_total / stream_mem_verify_fail_total`
    - `stream_pkt_sent_total / stream_pkt_recv_total`
    - `stream_pkt_bad_crc_total / stream_pkt_bad_magic_total`

---

## 选择与验收

- 选择：
  - `SNNDL_WORKLOAD_IMPL=stream`（或 `workload_impl=stream`）
- 验收关键点（100us）：
  - `stream_mem_verify_fail_total == 0`
  - `stream_mem_bytes_written_total > 0` 且 `stream_mem_bytes_read_total > 0`
  - `stream_pkt_sent_total > 0` 且（2+ node 场景）`stream_pkt_recv_total > 0`
