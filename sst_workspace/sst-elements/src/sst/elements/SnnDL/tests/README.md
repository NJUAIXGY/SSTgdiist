# tests/（测试与编译自检）

本目录存放 **测试/自检相关源码**。当前主要用于“包含路径/头文件依赖”类的编译自检，避免重构目录结构后出现隐式依赖问题。

## 默认内存语义（cacheline）

SnnDL 的默认体系结构口径是 **cacheline 粒度**（对齐 `memHierarchy GetS/GetX`）。与统计相关的回归（例如 dense microbench）应确保输出中包含
`effective_config.json`，并通过 validator 检查 granularity/traffic 口径一致性，避免把 row-streaming/DMA 假设混入默认结论。

## 主要内容

- `test_includes.cc`
  - 用于验证关键头文件可被独立包含并通过编译（不一定参与默认构建）。

## 使用建议

- 若后续增加新的模块目录或公共头文件，建议扩展 `test_includes.cc` 覆盖新增头，提前发现 include/循环依赖问题。
- 在 `SnnDL/` 目录可运行 `make test-compile` 进行快速编译自检（输出：`test_includes.o`）。
