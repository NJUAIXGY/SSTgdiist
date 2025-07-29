# NoC核心系统类

## 概述
本目录包含片上网络(NoC)系统的核心类实现，提供可复用的组件封装。

## 核心文件

### `noc_node_class.py`
包含两个主要类：

#### `NoCNode` - NoC节点类
封装了CPU、缓存、内存控制器的完整节点组件。

**主要方法：**
- `__init__()` - 初始化节点，支持计算节点和内存节点
- `_create_components()` - 创建节点的所有SST组件
- `_create_cpu_and_cache()` - 创建Miranda CPU和L1缓存
- `_create_memory_controller()` - 创建内存控制器和后端
- `_connect_components()` - 连接节点内部组件
- `get_cpu()`, `get_cache()`, `get_memory_controller()` - 获取组件引用
- `get_info()` - 获取节点信息

#### `NoCMesh` - NoC网格网络类
管理整个mesh网络的构建和配置。

**主要方法：**
- `__init__()` - 初始化mesh网络，配置内存节点位置
- `_create_nodes()` - 创建所有NoC节点
- `get_node()`, `get_all_nodes()` - 节点访问方法
- `get_compute_nodes()`, `get_memory_nodes()` - 按类型获取节点

## 使用示例

```python
import sst
from noc_node_class import NoCMesh

# 创建4x4网格，角落节点作为内存
mesh = NoCMesh(mesh_size_x=4, mesh_size_y=4)

# 获取节点
compute_nodes = mesh.get_compute_nodes()
memory_nodes = mesh.get_memory_nodes()
```

## 配置特性

- **CPU**: Miranda BaseCPU，SingleStream工作负载
- **缓存**: 8KB L1缓存，2路组相联
- **内存**: 128MB内存控制器，simpleMem后端
- **网络**: 基于SST memHierarchy的直连架构

## 设计原则

1. **模块化**: 清晰的组件分离和封装
2. **可复用**: 通过参数化配置支持不同规模
3. **稳定性**: 基于验证的稳定架构模式
4. **简洁性**: 移除复杂的测试代码，专注核心功能
