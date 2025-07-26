# 🚀 Core Systems Directory

## 核心系统说明
此目录包含Miranda CPU Mesh系统项目的核心实现文件，这些是项目的主要成果。

## 文件列表

### 🎯 主推荐系统
**cpu_mesh_simplified.py** - 简化的Miranda CPU网格系统
```
✅ 特点：
  • 稳定运行，无连接错误
  • 4x4网格拓扑，16个Miranda CPU核心
  • 分布式内存系统（每核心128MB）
  • 多种工作负载基准测试
  • 完整的统计数据收集
  • 高性能网络互连（40GiB/s带宽）

🏗️ 系统架构：
  • CPU模拟器: Miranda BaseCPU (真实指令执行)
  • 内存模型: 分布式simpleMem (避免复杂连接)
  • 网络拓扑: 2D Mesh + merlin endpoint
  • 链路性能: 40GiB/s 带宽, 50ps 延迟

🧠 工作负载分布：
  • 主控核心: STREAM基准测试 (内存带宽测试)
  • 内存控制器: 随机内存访问模式
  • I/O核心: 单流顺序访问模式
  • 计算核心: GUPS基准测试 (随机访问性能)
```

### 🔬 完整系统
**cpu_mesh_miranda.py** - 完整的Miranda CPU网格系统
```
🎯 特点：
  • 完整的memHierarchy实现
  • 复杂的缓存层次结构
  • 更真实的内存系统建模
  • 适合深度研究和分析

⚠️ 注意：
  • 可能存在连接复杂性问题
  • 需要更多调试和优化
  • 适合有经验的用户
```

### 🌲 DFS算法模拟系统
**cpu_mesh_dfs.py** - 用于DFS算法模拟的系统
```
🎯 特点：
  • 专门用于模拟深度优先搜索(DFS)算法
  • 基于完整系统的架构设计
  • 使用GUPS生成器模拟DFS访问模式
  • 为实现自定义DFS生成器提供框架

🧠 算法模拟：
  • 所有核心使用DFS/GUPS生成器
  • 模拟DFS遍历网格网络的行为
  • 通过内存访问模式体现DFS特性
```

## 运行方法

### 启动简化系统（推荐）
```bash
cd 02_Core_Systems/
sst cpu_mesh_simplified.py
```

### 启动完整系统
```bash
cd 02_Core_Systems/
sst cpu_mesh_miranda.py
```

### 启动DFS模拟系统
```bash
cd 02_Core_Systems/
sst cpu_mesh_dfs.py
```

## 系统参数配置

### 网格配置
```python
MESH_SIZE_X = 4        # 网格X维度
MESH_SIZE_Y = 4        # 网格Y维度
TOTAL_NODES = 16       # 总节点数
```

### 网络性能
```python
LINK_BANDWIDTH = "40GiB/s"  # 链路带宽
LINK_LATENCY = "50ps"       # 链路延迟
```

### CPU配置
```python
"clock": "2.4GHz"           # CPU时钟频率
"max_reqs_cycle": "2"       # 每周期最大请求数
```

## 输出文件

### 统计数据
- `simplified_miranda_stats.csv` - 简化系统统计数据
- `miranda_mesh_stats.csv` - 完整系统统计数据
- `dfs_simulation_stats.csv` - DFS模拟统计数据

### 关键指标
- CPU周期数和IPC
- 内存请求发出/返回计数
- 网络数据包发送/接收统计
- 路由器性能指标

## 性能特点

### 真实性
- 使用Miranda进行指令级精确仿真
- 真实的内存访问模式
- 实际的网络通信延迟

### 可扩展性
- 支持不同规模的网格配置
- 灵活的工作负载分配
- 模块化的组件设计

### 高性能
- 优化的网络拓扑
- 高带宽低延迟互连
- 并行处理能力

## 开发建议

1. **入门使用** - 从cpu_mesh_simplified.py开始
2. **参数调优** - 根据需求修改配置参数
3. **扩展开发** - 基于核心系统添加新功能
4. **算法模拟** - 使用cpu_mesh_dfs.py进行图算法模拟
5. **性能分析** - 使用统计数据进行优化

## 相关文档

- [DFS算法实现指南](DFS_IMPLEMENTATION.md) - DFS算法在SST中的实现说明

## 最后更新
2024年7月25日