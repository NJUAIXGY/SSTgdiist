# components/multicore/（MultiCorePE 参数解析模块）

本目录用于承载 **MultiCorePE 的构造期参数解析**，以降低 `components/MultiCorePE.cc` 中 `params.find(...)` 的噪音。

## 内存粒度口径（默认：cacheline）

本目录仅处理构造期参数解析，不参与内存事务实现；但相关参数（例如 cacheline 大小/步进预算等）需要与平台默认语义保持一致：**cacheline 是默认的外部搬运单位**（与
`memHierarchy` 统计对齐）。任何显式的 row-streaming/DMA 假设应通过独立参数与 `effective_config.json` 落盘标注。

## 设计原则

- **不新增运行期组件/装配点**：仅新增解析函数与配置结构体；SST ELI 注册对象仍只有 `MultiCorePE` 本体。
- **不改变参数面**：所有参数名/默认值保持与 `MultiCorePE` 现有实现一致（仅搬运解析位置）。

## 文件

- `MultiCorePEConfig.{h,cc}`
  - `parseMultiCorePEConfig(const SST::Params&) -> MultiCorePEConfig`
  - 负责读取 `clock/num_cores/neurons_per_core/neurons_per_pe/global_neuron_base/...` 等参数并返回结构化配置。
