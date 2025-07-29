# SSTgdiist - Miranda CPU Mesh System v3.0

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![SST](https://img.shields.io/badge/SST-13.0+-orange.svg)
![Version](https://img.shields.io/badge/version-v3.0-success.svg)

一个基于SST（Structural Simulation Toolkit）框架的Miranda CPU网格系统仿真项目，实现了可复用的面向对象类架构，支持灵活配置的多核处理器系统仿真。

## 🚀 v3.0 项目特点

- **🏗️ 完全类封装**: `MirandaCPUMeshSystem` 可复用类架构
- **🎮 简化使用**: 一行代码构建完整系统
- **⚙️ 灵活配置**: 支持任意网格大小和系统参数
- **🧪 完整测试**: 5个测试场景全部通过验证
- **📚 详细文档**: 类使用指南和多个示例
- **🔧 模块化设计**: 易于扩展和维护的架构

## 📋 系统要求

### 必需软件
- **SST Core** (≥ 13.0)
- **SST Elements** 
- **Miranda CPU组件**
- **Merlin网络库**
- **Python** (≥ 3.8)

### 推荐环境
- Ubuntu 20.04+ 或 CentOS 8+
- 16GB+ RAM (用于大规模仿真)
- 多核处理器 (仿真加速)

## 🛠️ 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/NJUAIXGY/SSTgdiist.git
cd SSTgdiist
```

### 2. 使用新的类架构（推荐）
```bash
# 运行基于类的版本
sst 02_Core_Systems/cpu_mesh_miranda_class_based.py

# 查看使用示例
sst 02_Core_Systems/example_usage.py

# 测试类功能（非SST环境）
python3 02_Core_Systems/test_class_functionality.py
```

### 3. 在代码中使用
```python
from miranda_cpu_mesh_system import MirandaCPUMeshSystem

# 基本使用
system = MirandaCPUMeshSystem()
system.build_system()
system.configure_simulation()

# 自定义配置
system = MirandaCPUMeshSystem(
    mesh_size_x=8, mesh_size_y=8,
    link_bandwidth="100GiB/s",
    cpu_clock="4.0GHz"
)

# 便利函数（一行代码）
from miranda_cpu_mesh_system import build_and_configure_system
system = build_and_configure_system(mesh_size_x=6, mesh_size_y=4)
```
./quick_start.sh

# 或手动运行主系统
cd 02_Core_Systems/
sst cpu_mesh_simplified.py
```

### 4. 查看结果
```bash
# 使用分析工具
cd 04_Analysis_Tools/
python analysis_tool.py
```

## 📁 项目结构

```
Miranda_CPU_Mesh_Project/
├── 01_Documentation/          # 📚 技术文档和报告
│   ├── README.md
│   ├── Miranda_CPU_Technical_Report_CN.md
│   ├── Miranda_CPU_Technical_Report_EN.md
│   └── *.pdf
├── 02_Core_Systems/           # 🚀 核心系统实现
│   ├── cpu_mesh_simplified.py    # 主要系统（推荐）
│   └── cpu_mesh_miranda.py       # 完整系统
├── 03_Experimental_Systems/   # 🔬 实验性版本
├── 04_Analysis_Tools/         # 🔧 数据分析工具
├── 05_Test_Systems/           # 🧪 测试和验证
├── 06_Results_Data/           # 📊 仿真结果数据
├── 07_Legacy_Experiments/     # 📁 早期实验
├── quick_start.sh             # 快速启动脚本
└── README.md                  # 项目说明
```

## 🎯 核心功能

### Miranda CPU仿真
- **指令级仿真**: 真实的CPU指令执行
- **内存层次**: 分布式内存控制器
- **工作负载**: 多种基准测试程序

### 网络拓扑
- **4×4 Mesh**: 16个节点的网格网络
- **高性能链路**: 40GiB/s带宽，50ps延迟
- **端点通信**: Merlin endpoint协议

### 分析工具
- **性能统计**: CPU周期、内存访问、网络流量
- **数据可视化**: 图表和热力图
- **结果导出**: CSV格式的详细数据

## 📊 工作负载分布

| 核心类型 | 位置 | 工作负载 | 描述 |
|---------|------|----------|------|
| 主控核心 | (0,0) | STREAM | 内存带宽测试 |
| 内存控制器 | (3,3) | 随机访问 | 内存控制器仿真 |
| I/O核心 | 边缘 | 单流访问 | I/O操作仿真 |
| 计算核心 | 中心 | GUPS | 随机访问性能测试 |

## 🔧 配置参数

### 系统规模
```python
MESH_SIZE_X = 4      # 网格宽度
MESH_SIZE_Y = 4      # 网格高度
TOTAL_NODES = 16     # 总节点数
```

### 网络性能
```python
LINK_BANDWIDTH = "40GiB/s"  # 链路带宽
LINK_LATENCY = "50ps"       # 链路延迟
```

### CPU配置
```python
clock = "2.4GHz"            # CPU时钟频率
max_reqs_cycle = "2"        # 每周期最大请求数
```

## 📈 性能指标

主要统计指标：
- **CPU性能**: 周期数、IPC、吞吐量
- **内存性能**: 访问延迟、带宽利用率
- **网络性能**: 包传输量、延迟分布
- **系统效率**: 资源利用率、负载均衡

## 🔬 实验和测试

### 基准测试
- **STREAM**: 内存带宽基准测试
- **GUPS**: 随机内存访问性能
- **自定义负载**: 用户定义的访问模式

### 验证测试
- **基础功能**: 系统启动和基本操作
- **性能测试**: 不同负载下的性能表现
- **稳定性**: 长时间运行测试

## 📚 文档

- [中文技术报告](01_Documentation/Miranda_CPU_Technical_Report_CN.md)
- [English Technical Report](01_Documentation/Miranda_CPU_Technical_Report_EN.md)
- [API文档](01_Documentation/)
- [使用示例](05_Test_Systems/)

## 🤝 贡献指南

欢迎贡献！请遵循以下步骤：

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 联系方式

- **项目维护者**: [Your Name]
- **邮箱**: your.email@example.com
- **项目链接**: [https://github.com/YOUR_USERNAME/miranda-cpu-mesh-system](https://github.com/YOUR_USERNAME/miranda-cpu-mesh-system)

## 🙏 致谢

- [SST Project](http://sst-simulator.org/) - 仿真框架
- [Miranda CPU](https://github.com/sstsimulator/sst-elements) - CPU仿真器
- [Merlin](https://github.com/sstsimulator/sst-elements) - 网络仿真库

## 📝 更新日志

### v1.0.0 (2025-07-26)
- ✅ 初始版本发布
- ✅ 4×4 Miranda CPU网格系统
- ✅ 完整的分析工具链
- ✅ 中英文技术文档
- ✅ 多种基准测试工作负载

---

⭐ 如果这个项目对您有帮助，请给个Star！
