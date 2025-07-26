# Miranda CPU Mesh System - 详细使用指南

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![SST](https://img.shields.io/badge/SST-13.0+-orange.svg)

这是Miranda CPU网格系统的详细使用指南，帮助您快速上手和深入使用本仿真项目。

## 🎯 项目概述

本项目已精简至核心功能，专注于提供稳定可用的CPU网格仿真系统：

- **🚀 核心系统**: 2个稳定的仿真系统
- **📚 完整文档**: 中英文技术文档  
- **🔧 易于使用**: 简化的启动和运行流程
- **⚡ 高性能**: 4×4网格，16核CPU，40GiB/s网络

## 📁 项目结构

```
SSTgdiist/
├── 01_Documentation/          # 📚 技术文档
│   ├── README.md                          # 文档说明
│   ├── 技术报告_Miranda_CPU_Mesh系统.md      # 中文技术报告
│   ├── Miranda_CPU_Mesh_Technical_Report_EN.md # 英文技术报告  
│   ├── 技术报告_Miranda_CPU_Mesh系统.pdf
│   └── Miranda_CPU_Mesh_Technical_Report_EN.pdf
├── 02_Core_Systems/           # 🚀 核心仿真系统
│   ├── README.md                          # 系统说明
│   ├── cpu_mesh_simplified.py            # 简化版系统（推荐）
│   └── cpu_mesh_miranda.py               # 完整版系统
├── quick_start.sh             # ⚡ 快速启动脚本
├── README.md                  # 📄 项目说明
├── README_SIMPLIFIED.md       # 📖 本文件：详细使用指南
└── PROJECT_STATUS_SIMPLIFIED.md # 📊 精简报告
```

## 🛠️ 安装和环境配置

### 系统要求
- **操作系统**: Ubuntu 20.04+ 或 CentOS 8+
- **内存**: 16GB+ RAM (推荐)
- **处理器**: 多核处理器 (加速仿真)

### 必需软件
- **SST Core** (≥ 13.0)
- **SST Elements** 
- **Miranda CPU组件**
- **Merlin网络库**
- **Python** (≥ 3.8)

### 环境检查
```bash
# 检查SST安装
sst --version

# 检查Miranda组件
sst-info miranda

# 检查Merlin网络库
sst-info merlin
```

## 🚀 快速开始

### 方法1: 使用快速启动脚本（推荐）
```bash
# 克隆项目
git clone https://github.com/NJUAIXGY/SSTgdiist.git
cd SSTgdiist

# 运行启动脚本
./quick_start.sh
```

### 方法2: 手动运行
```bash
# 进入核心系统目录
cd 02_Core_Systems/

# 运行简化版系统（推荐新手）
sst cpu_mesh_simplified.py

# 或运行完整版系统（高级用户）
sst cpu_mesh_miranda.py
```

## 🎯 核心系统说明

### 1. cpu_mesh_simplified.py （推荐）
- **特点**: 简化配置，稳定运行
- **适用**: 新手入门，基础测试
- **运行时间**: 约2-5分钟
- **输出**: 基本性能统计

### 2. cpu_mesh_miranda.py （完整版）
- **特点**: 完整功能，更多配置选项
- **适用**: 深入研究，自定义配置
- **运行时间**: 约5-15分钟
- **输出**: 详细性能分析

## 📊 系统架构详解

### 网格拓扑
```
(0,0)-----(0,1)-----(0,2)-----(0,3)
  |         |         |         |
(1,0)-----(1,1)-----(1,2)-----(1,3)
  |         |         |         |
(2,0)-----(2,1)-----(2,2)-----(2,3)
  |         |         |         |
(3,0)-----(3,1)-----(3,2)-----(3,3)
```

### 核心配置
- **总节点数**: 16个 (4×4网格)
- **CPU频率**: 2.4GHz
- **网络带宽**: 40GiB/s
- **网络延迟**: 50ps
- **内存**: 分布式配置

### 工作负载分布
| 位置 | 核心类型 | 工作负载 | 描述 |
|------|----------|----------|------|
| (0,0) | 主控核心 | STREAM | 内存带宽基准测试 |
| (3,3) | 内存控制器 | 随机访问 | 内存控制器仿真 |
| 边缘节点 | I/O核心 | 单流访问 | I/O操作仿真 |
| 中心节点 | 计算核心 | GUPS | 随机访问性能测试 |

## 📈 运行结果分析

### 输出文件类型
仿真完成后会生成以下类型的文件：

```bash
# 查看生成的结果文件
ls -la *.txt *.csv *.out

# 典型输出文件示例
miranda_stats.txt      # Miranda CPU统计
network_stats.csv      # 网络流量统计
memory_stats.txt       # 内存访问统计
```

### 关键性能指标

#### CPU性能
- **IPC** (Instructions Per Cycle): 每周期指令数
- **总周期数**: 仿真执行的总CPU周期
- **吞吐量**: 指令执行速率

#### 内存性能
- **访问延迟**: 内存访问平均延迟
- **带宽利用率**: 内存带宽使用情况
- **命中率**: 缓存命中率

#### 网络性能
- **包传输量**: 网络包传输统计
- **链路利用率**: 各链路的使用情况
- **延迟分布**: 端到端通信延迟

### 结果解读示例
```
=== Miranda CPU Statistics ===
Total Cycles: 1,234,567
Instructions Completed: 987,654
IPC: 0.80
Memory Requests: 456,789

=== Network Statistics ===
Total Packets: 123,456
Average Latency: 150ns
Link Utilization: 65%
```

## 🔧 自定义配置

### 修改系统规模
```python
# 在系统文件中修改以下参数
MESH_SIZE_X = 4      # 网格宽度
MESH_SIZE_Y = 4      # 网格高度
TOTAL_NODES = 16     # 总节点数
```

### 调整网络性能
```python
LINK_BANDWIDTH = "40GiB/s"  # 链路带宽
LINK_LATENCY = "50ps"       # 链路延迟
FLIT_SIZE = "8B"           # 数据包大小
```

### 修改CPU配置
```python
CPU_CLOCK = "2.4GHz"        # CPU时钟频率
MAX_REQS_CYCLE = "2"        # 每周期最大请求数
CACHE_SIZE = "32KiB"        # 缓存大小
```

## 🔬 基准测试

### STREAM基准测试
- **目的**: 测试内存带宽
- **模式**: 向量操作 (Copy, Scale, Add, Triad)
- **适用**: 内存密集型应用评估

### GUPS基准测试
- **目的**: 测试随机内存访问
- **模式**: 随机表查找更新
- **适用**: 数据库、图算法等应用

### 自定义工作负载
可以通过修改Miranda生成器参数来创建自定义工作负载：

```python
# 示例：创建自定义访问模式
miranda_gen = sst.Component("miranda_gen", "miranda.BaseCPU")
miranda_gen.addParams({
    "generator": "CustomGenerator",
    "generatorParams.pattern": "sequential",  # 或 "random", "stride"
    "generatorParams.count": "1000000",
    "generatorParams.address_start": "0x1000",
})
```

## 🐛 常见问题排查

### 问题1: SST组件未找到
```bash
错误: Component 'miranda.BaseCPU' not found
解决: 检查SST Elements安装，确保Miranda组件可用
验证: sst-info miranda
```

### 问题2: 内存不足
```bash
错误: 仿真运行缓慢或崩溃
解决: 减少仿真规模或增加系统内存
建议: 至少16GB RAM用于标准配置
```

### 问题3: 网络配置错误
```bash
错误: 网络拓扑连接失败
解决: 检查路由器端口配置和链路连接
验证: 确保端口数量与拓扑匹配
```

## 📚 深入学习资源

### 技术文档
- [中文技术报告](01_Documentation/技术报告_Miranda_CPU_Mesh系统.md) - 系统架构详解
- [English Technical Report](01_Documentation/Miranda_CPU_Mesh_Technical_Report_EN.md) - System architecture
- [文档目录](01_Documentation/) - 所有技术文档

### SST框架资源
- [SST官方网站](http://sst-simulator.org/) - 框架文档和教程
- [SST Elements](https://github.com/sstsimulator/sst-elements) - 组件库文档
- [Miranda CPU](https://github.com/sstsimulator/sst-elements/tree/devel/src/sst/elements/miranda) - CPU仿真器文档

### 相关论文和资料
- SST框架原理和应用
- Miranda处理器仿真技术
- Mesh网络拓扑设计
- 高性能计算系统仿真方法

## 🤝 贡献和支持

### 报告问题
如果遇到问题，请：
1. 检查常见问题排查部分
2. 查看技术文档
3. 在GitHub仓库提交issue

### 贡献代码
欢迎贡献！请遵循：
1. Fork项目
2. 创建功能分支
3. 提交清晰的代码和文档
4. 创建Pull Request

### 获取帮助
- **GitHub Issues**: 报告bug和功能请求
- **技术文档**: 详细的系统说明
- **代码注释**: 系统文件中的详细注释

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

---

🎯 希望这份指南能帮助您成功使用Miranda CPU网格系统！如有问题，请查看技术文档或提交issue。
