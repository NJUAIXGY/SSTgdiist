# DFS算法在SST框架中的实现指南

## 概述

本文档说明如何在SST框架中实现深度优先搜索(DFS)算法的模拟。由于SST框架本身不提供DFS生成器，我们需要通过自定义方式实现或使用现有生成器模拟DFS行为。

## DFS算法特点

DFS算法的核心特点是：
1. 从起始节点开始深度遍历
2. 访问一个节点的所有未访问邻居
3. 使用栈结构或递归实现
4. 直到无法继续深入才回溯

## 在网格网络中模拟DFS

在4x4网格网络中，每个节点可以看作图中的一个顶点，节点间的连接表示图的边。

### 模拟方法

由于SST框架中的Miranda生成器不直接支持DFS算法，我们可以通过以下方式模拟：

1. **使用现有生成器模拟**：
   - 使用GUPS生成器模拟随机访问模式
   - 使用RandomGenerator模拟不规则访问模式
   - 调整参数使访问模式接近DFS特性

2. **自定义生成器实现**（推荐方式）：
   - 创建C++插件实现真正的DFS生成器
   - 在SST Elements中添加自定义生成器组件

## 自定义DFS生成器实现步骤

### 1. 创建C++生成器类

需要在SST Elements中创建一个新的生成器类，例如`DFSBenchGenerator`：

```cpp
// DFSBenchGenerator.h
class DFSBenchGenerator : public RequestGenerator {
    // 实现DFS算法逻辑
    // 生成符合DFS访问模式的内存请求
};
```

### 2. 注册生成器组件

在SST Elements中注册新的生成器组件，使其可以在Python配置文件中使用。

### 3. 配置使用自定义生成器

在Python配置文件中使用自定义生成器：

```python
cpu_core.addParams({
    "generator": "miranda.DFSBenchGenerator",
    "generatorParams.count": "1000",
    "generatorParams.start_node": "0",
    "generatorParams.grid_size": "4x4"
})
```

## 当前实现方案

在当前项目中，我们采用以下方式模拟DFS算法：

1. 所有CPU核心使用GUPS生成器（最接近DFS随机访问特性的现有生成器）
2. 通过调整参数优化访问模式
3. 利用网格网络拓扑特性模拟DFS遍历行为

## 运行DFS模拟

```bash
cd 02_Core_Systems/
sst cpu_mesh_dfs.py
```

## 结果分析

运行后将生成`../03_Output_Data/dfs_simulation_stats.csv`文件，包含：
- CPU周期数和性能指标
- 内存请求统计
- 网络包传输统计
- 路由器性能数据

所有SST模拟的输出数据现在统一存放在`03_Output_Data`目录中。

## 扩展建议

1. **实现真正的DFS生成器**：
   - 在SST Elements中添加自定义DFS生成器
   - 实现真实的DFS遍历算法

2. **优化访问模式**：
   - 调整生成器参数使访问模式更接近DFS特性
   - 添加访问历史记录避免重复访问

3. **可视化DFS遍历过程**：
   - 添加额外的统计项追踪遍历路径
   - 生成遍历路径图

## 总结

虽然SST框架本身不提供DFS生成器，但通过合理配置现有组件和参数，我们可以有效模拟DFS算法的行为。对于更精确的模拟，建议实现自定义的DFS生成器组件。