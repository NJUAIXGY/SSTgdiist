# services/synapse/common/（Synapse 公共工具：BCSR 元信息口径）

本目录存放 **Synapse 域内部共享的轻量公共工具**，用于避免 weights/route/stimulus 对同一套 BCSR 元信息口径出现重复实现或口径漂移。

> 边界原则：`common/` 只放“小而稳定”的 helper/结构体（通常是 header-only），不承载任何事务状态机与 I/O 编排。

## 默认内存语义（cacheline）与显式搬运假设

- SnnDL 平台核默认以 **cacheline** 作为对外搬运/统计单位（对齐 `memHierarchy` 的 `GetS/GetX`）。
- BCSR meta/offset 的存在并不意味着必须按“整行/大块”搬运：任何 row-streaming/DMA 或更大 granule 读都必须被当作“显式架构假设”单列，并在输出中通过
  `effective_config.json` 与 granule 统计闭环验证。

---

## 主要内容

### `BcsrMeta.h`
- **定位**：BCSR `.meta.json` 的最小解析与校验工具（通用口径：rows/cols/br/bc/idx_bytes/val_bytes + offsets/total_blocks）
- **提供能力**：
  - `parseBcsrMetaJsonFile(meta_path, out)`：从 `.meta.json` 提取必要字段（容忍字段缺省）
  - `validateBcsrMetaAgainstFile(meta, file_size, rows_for_rowptr, err_out)`：对 offset/区间/必要字节数做 fail-fast 校验
  - 常用辅助：`bcsrNumBlockRows()` / `bcsrBytesPerBlock()` 等
- **典型调用方**：
  - `services/synapse/route/BcsrRouteBuilder.*`（路由构建侧读取/校验 meta）
  - `services/synapse/weights/*`（权重侧如需 meta 口径校验，也应优先复用该工具）

---

## 约束与建议

- **禁止**：在 `common/` 中引入 StandardMem/NoC/控制层私有对象。
- **建议**：所有 BCSR offset 口径统一从 `.meta.json` 注入，并优先通过 `validateBcsrMetaAgainstFile()` 做范围校验，避免静默读取 0/截断导致的发放归零问题。
