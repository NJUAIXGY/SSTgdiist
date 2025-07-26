# Miranda CPU Mesh System Project

## 项目概述
这是一个基于SST (Structural Simulation Toolkit) 框架的Miranda CPU网格系统仿真项目。该项目实现了一个4x4网格拓扑的CPU系统，使用Miranda处理器进行指令级精确仿真。

## 项目创建日期
**2024年7月25日**

## 目录结构说明

### 📚 01_Documentation/
**文档和报告**
- `技术报告_Miranda_CPU_Mesh系统.md` - 中文技术报告（Markdown格式）
- `技术报告_Miranda_CPU_Mesh系统.pdf` - 中文技术报告（PDF格式）
- `Miranda_CPU_Mesh_Technical_Report_EN.md` - 英文技术报告（Markdown格式）
- `Miranda_CPU_Mesh_Technical_Report_EN.pdf` - 英文技术报告（PDF格式）

### 🚀 02_Core_Systems/
**核心系统实现**
- `cpu_mesh_simplified.py` - **主要系统** - 简化的Miranda CPU网格系统
- `cpu_mesh_miranda.py` - 完整的Miranda CPU网格系统（复杂版本）

### 🔬 03_Experimental_Systems/
**实验性系统**
- 各种CPU网格系统的实验性实现
- Miranda处理器的不同配置
- 内存系统和网络拓扑实验

### 🔧 04_Analysis_Tools/
**分析工具**
- `analyze_*.py` - 各种数据分析脚本
- `visualize_*.py` - 可视化工具
- `traffic_analysis.py` - 网络流量分析
- `*summary*.py` - 项目总结工具

### 🧪 05_Test_Systems/
**测试系统**
- 各种测试配置和简化版本
- 基础功能验证系统
- 最小化测试实例

### 📊 06_Results_Data/
**仿真结果数据**
- `*.csv` - 仿真统计数据
- 性能分析结果
- 网络流量数据

### 📁 07_Legacy_Experiments/
**早期实验**
- 开发过程中的早期实验
- 遗留代码和测试版本

## 主要系统介绍

### 🎯 推荐使用：cpu_mesh_simplified.py
这是项目的**主要成果**，特点：
- ✅ 稳定运行，无连接错误
- ✅ 4x4网格拓扑，16个Miranda CPU核心
- ✅ 分布式内存系统（每核心128MB）
- ✅ 多种工作负载：STREAM、GUPS、随机访问、单流访问
- ✅ 完整的统计数据收集
- ✅ 高性能网络互连（40GiB/s带宽）

### 系统架构
```
🏗️ 系统架构:
   • 网格规模: 4×4 = 16 个Miranda CPU核心
   • CPU模拟器: Miranda BaseCPU (真实指令执行)
   • 内存模型: 分布式简单内存 (每核心128MB)
   • 网络拓扑: 2D Mesh + endpoint通信
   • 链路性能: 40GiB/s 带宽, 50ps 延迟

🧠 CPU工作负载分布:
   • 主控核心: STREAM基准测试 (内存带宽测试)
   • 内存控制器: 随机内存访问模式
   • I/O核心: 单流顺序访问模式
   • 计算核心: GUPS基准测试 (随机访问性能)
```

## 如何运行

### 运行主系统
```bash
cd 02_Core_Systems/
sst cpu_mesh_simplified.py
```

### 分析结果
```bash
cd 04_Analysis_Tools/
python analyze_results.py
```

### 查看文档
```bash
cd 01_Documentation/
# 查看技术报告（PDF或Markdown格式）
```

## 技术特点

- **真实仿真**: 使用Miranda进行指令级精确模拟
- **可扩展**: 支持不同规模的网格配置
- **高性能**: 优化的网络互连和内存系统
- **多样化工作负载**: 包含多种基准测试和访问模式
- **完整统计**: 详细的性能分析和监控数据

## 开发历程

1. **基础测试** - 简单的CPU和网络测试
2. **网格构建** - 2D mesh拓扑实现
3. **Miranda集成** - 真实CPU仿真器集成
4. **内存系统** - 分布式内存架构
5. **工作负载优化** - 多种基准测试配置
6. **性能调优** - 系统参数优化
7. **文档完善** - 技术报告和使用指南

## 成果总结

✅ 成功实现基于SST框架的Miranda CPU网格系统  
✅ 验证了4x4网格拓扑的可行性和性能  
✅ 集成了多种真实工作负载和基准测试  
✅ 提供了完整的技术文档和分析工具  
✅ 建立了可扩展的仿真平台架构  

## 联系信息
项目创建者：SST开发团队  
技术支持：Miranda CPU网格系统项目组  
最后更新：2024年7月25日
