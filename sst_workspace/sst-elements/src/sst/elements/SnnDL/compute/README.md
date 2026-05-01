# compute/（可替换计算核心层）

本目录存放 **可插拔 compute core 接口与默认 SNN 核心实现**。目标是让 SnnDL 支持未来“替换核心计算范式”，而无需改动平台壳（CoreShell：`control/SnnPESubComponent`）。

## 职责

- 定义 `ISnnComputeCore` 的统一契约：输入、阶段回调、周期收敛、输出事件拉取、统计等。
- 提供默认实现 `DefaultSnnComputeCore`（当前对应 SNN 动力学/学习/验证）。
- 聚合与 compute core 强相关的算法/数据结构：神经模型、学习核心、权重验证逻辑等。

## 主要内容

- `ISnnComputeCore.h`
  - `ISnnComputeCore` 接口、核心数据结构（`FireEvent` 等）与工厂声明 `createComputeCoreByName()`。
- `IWeightAwareComputeCore.h`
  - **可选扩展接口**：仅当某 compute core 需要“权重/缓存语义”时实现（Phase5.4 从主接口迁出）。
- `SnnComputeCore.{h,cc}`
  - `DefaultSnnComputeCore`：默认 SNN 实现（动力学/学习/验证）。
  - `createComputeCoreByName()`：工厂实现（当前支持 `default`/`snn`，未知名称返回空并由控制层回退）。
- `SnnCoreEngine.{h,cc}`：动力学引擎/内核执行器（Default core 使用）。
- `SnnNeuronModel.h`：神经元模型接口与实现选择（LIF 等）。
- `SnnLearningCore.{h,cc}`：学习/梯度累加模块（可选启用）。
- `SynapseManager.h`：突触/连接管理辅助结构（与 compute 侧数据布局相关）。

## 依赖边界（建议）

- `compute/` 应尽量只依赖 `api/`、`events/` 与标准库。
- 若需要访问权重/缓存/内存，统一通过 `ComputeCoreContext.weight_reader`（`api/SnnWeightReader.h` 的 `IWeightReader`）注入，而不是直接触碰控制层私有成员。
- 若某 compute 确实需要“权重请求/缓存 key”等 legacy 语义，使用 `IWeightAwareComputeCore` 扩展接口承载，避免污染 `ISnnComputeCore` 主契约。
- 接口行为冻结与契约说明：优先维护 `../ISnnComputeCore_SPEC.md`（仓库根部），此目录文档只补充设计与实现细节。

## 扩展指南（新增计算范式）

- 新增一个实现类 `class XxxComputeCore : public ISnnComputeCore`，并：
  - 明确自身 `ComputeCoreCapabilities`；
  - 实现 `endCycle/endCycleCandidates + drainOutputs` 的一致语义（输出由控制层统一路由）。
- 在 `createComputeCoreByName()` 中注册 `name -> XxxComputeCore`；
- 在仿真脚本/参数中设置 `compute_core_impl=name`。

---

## 内存建模口径（默认 cacheline）与 compute 的关系

compute 层不应假设“权重一次读就是整行/整块”：

- 默认体系结构语义是 cacheline（memHierarchy）事务；是否存在更大粒度（row-streaming/DMA）属于上层 workload/内存前端的显式架构假设。
- compute 只接收“已解析后的权重值/向量”（由 synapse/weights 或 workload 提供），不直接基于 StandardMem 的请求粒度做推断。
