# NoC节点类封装使用指南

本目录包含了封装的NoC（片上网络）节点类，可以在不同的测试脚本中复用。

## 📁 文件结构

```
02_Core_Systems/
├── noc_node_class.py          # NoC节点和Mesh网络封装类
├── test_noc_class.py          # 基本使用示例
├── advanced_noc_tests.py      # 高级测试场景
├── cpu_mesh_miranda.py        # 原始实现（作为参考）
└── README_NOC_CLASS.md        # 本文件
```

## 🎯 主要类介绍

### NoCNode 类
封装单个NoC节点，包含：
- Miranda CPU核心
- L1缓存
- 内存控制器
- 路由器
- 自动工作负载配置

### NoCMesh 类
管理整个Mesh网络，包含：
- 自动创建所有节点
- 构建Mesh连接
- 统计配置管理
- 系统信息总结

## 🚀 快速开始

### 1. 基本使用

```python
from noc_node_class import NoCMesh
import sst

# 创建4x4 mesh网络
mesh = NoCMesh(mesh_size_x=4, mesh_size_y=4)

# 设置统计输出
mesh.setup_statistics_output("output/stats.csv")
mesh.enable_all_statistics()

# 打印系统信息
mesh.print_summary()

# 设置仿真时间并开始
sst.setProgramOption("stop-at", "100us")
```

### 2. 自定义配置

```python
# 创建自定义规模和参数的网络
mesh = NoCMesh(
    mesh_size_x=8, 
    mesh_size_y=8,
    link_bandwidth="100GiB/s",
    link_latency="25ps"
)

# 获取特定节点进行自定义配置
node = mesh.get_node(0)
info = node.get_info()
print(f"节点信息: {info}")
```

### 3. 单节点测试

```python
from noc_node_class import NoCNode

# 创建单个节点用于测试
node = NoCNode(
    node_id=0, x=0, y=0,
    mesh_size_x=1, mesh_size_y=1
)

# 启用统计
node.enable_statistics()
```

## 📊 运行测试

### 基本测试
```bash
# 在SST环境中运行
sst test_noc_class.py

# 或指定测试模式
sst test_noc_class.py basic     # 基本4x4测试
sst test_noc_class.py custom    # 自定义2x2测试
sst test_noc_class.py single    # 单节点测试
```

### 高级测试场景
```bash
# 性能分析测试
sst advanced_noc_tests.py performance

# 可扩展性研究 (指定mesh规模)
sst advanced_noc_tests.py scalability 6

# 容错性测试
sst advanced_noc_tests.py fault

# 自定义工作负载测试
sst advanced_noc_tests.py custom
```

## 🛠️ 类接口详解

### NoCNode 主要方法

| 方法 | 描述 |
|------|------|
| `__init__(node_id, x, y, ...)` | 初始化节点 |
| `get_router()` | 获取路由器组件 |
| `get_cpu()` | 获取CPU组件 |
| `get_cache()` | 获取L1缓存组件 |
| `get_memory_controller()` | 获取内存控制器组件 |
| `get_info()` | 获取节点信息字典 |
| `enable_statistics()` | 启用节点统计收集 |
| `connect_to_router(other, ...)` | 连接到其他路由器 |

### NoCMesh 主要方法

| 方法 | 描述 |
|------|------|
| `__init__(mesh_size_x, mesh_size_y, ...)` | 初始化Mesh网络 |
| `get_node(node_id)` | 获取指定节点 |
| `get_all_nodes()` | 获取所有节点列表 |
| `setup_statistics_output(path)` | 设置统计输出文件 |
| `enable_all_statistics()` | 启用所有统计收集 |
| `print_summary()` | 打印系统配置总结 |

## 🎨 自定义工作负载

您可以通过修改 `NoCNode._configure_workload()` 方法来自定义工作负载：

```python
class CustomNoCNode(NoCNode):
    def _configure_workload(self):
        # 自定义工作负载配置
        if self.node_id == 0:
            # 特殊配置节点0
            self.cpu.addParams({
                "generator": "miranda.CustomGenerator",
                # ... 其他参数
            })
        else:
            # 默认配置
            super()._configure_workload()
```

## 🔍 输出文件

运行测试后，统计数据将保存在以下位置：
- `/home/anarchy/SST/sst_output_data/` 目录
- CSV格式，包含详细的性能统计

### 主要统计项
- **CPU统计**: cycles, reqs_issued, reqs_returned
- **网络统计**: send_packet_count, recv_packet_count
- **缓存统计**: cache_hits, cache_misses
- **内存统计**: memory_requests, access_latency

## 🧪 测试场景

### 1. 性能分析 (`performance`)
- 目标：测量网络延迟和吞吐量
- 配置：4x4 mesh，标准参数
- 仿真时间：200μs

### 2. 可扩展性研究 (`scalability`)
- 目标：分析网络规模对性能的影响
- 配置：可变mesh规模
- 仿真时间：动态调整

### 3. 容错性测试 (`fault`)
- 目标：测试网络故障恢复能力
- 配置：5x5 mesh，冗余路径
- 仿真时间：150μs

### 4. 自定义工作负载 (`custom`)
- 目标：优化的应用场景测试
- 配置：3x3 mesh，高性能参数
- 仿真时间：100μs

## 💡 使用建议

1. **开发阶段**: 使用小规模mesh（2x2或3x3）进行快速测试
2. **性能评估**: 使用4x4或更大规模进行完整评估
3. **参数调优**: 通过修改link_bandwidth和link_latency优化性能
4. **统计分析**: 利用CSV输出进行详细的性能分析

## ⚠️ 注意事项

1. 确保SST环境正确配置
2. 输出目录需要有写入权限
3. 大规模mesh网络需要更多内存和计算时间
4. 统计文件可能很大，注意磁盘空间

## 🔧 扩展开发

要添加新功能：

1. **新的工作负载类型**: 修改 `_configure_workload()` 方法
2. **新的网络拓扑**: 继承 `NoCMesh` 类并重写 `_build_mesh_connections()`
3. **新的统计项**: 在 `enable_statistics()` 方法中添加
4. **新的测试场景**: 在 `advanced_noc_tests.py` 中添加新方法

这个封装设计使得NoC系统可以轻松地在不同项目中复用，同时保持了高度的可定制性。
