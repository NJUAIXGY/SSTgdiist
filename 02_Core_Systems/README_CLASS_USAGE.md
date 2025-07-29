# Miranda CPU Mesh System 类封装

## 概述

本文档介绍了将原始的 `cpu_mesh_miranda.py` 脚本封装为可复用类的实现。封装后的系统提供了更好的模块化、可配置性和复用性。

## 文件结构

```
02_Core_Systems/
├── cpu_mesh_miranda.py              # 原始脚本
├── miranda_cpu_mesh_system.py       # 封装的类文件
├── cpu_mesh_miranda_class_based.py  # 基于类的替换版本
├── example_usage.py                 # 使用示例
└── README_CLASS_USAGE.md           # 本文档
```

## 核心类：MirandaCPUMeshSystem

### 主要特性

1. **完全封装**: 将所有系统构建逻辑封装在类中
2. **可配置**: 支持灵活的参数配置
3. **可复用**: 可在多个脚本中重复使用
4. **模块化**: 清晰的方法分离，易于维护和扩展
5. **向后兼容**: 保持与原始脚本相同的功能

### 类参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `mesh_size_x` | int | 4 | Mesh网格X维度大小 |
| `mesh_size_y` | int | 4 | Mesh网格Y维度大小 |
| `link_bandwidth` | str | "40GiB/s" | 链路带宽 |
| `link_latency` | str | "50ps" | 链路延迟 |
| `cpu_clock` | str | "2.4GHz" | CPU时钟频率 |
| `cache_size` | str | "32KiB" | L1缓存大小 |
| `memory_size` | str | "128MiB" | 本地内存大小 |
| `output_dir` | str | "/home/anarchy/SST/sst_output_data" | 统计输出目录 |
| `verbose` | bool | True | 是否启用详细输出 |

### 主要方法

#### 1. `build_system()`
构建完整的Miranda CPU Mesh系统，包括：
- 创建所有CPU核心和路由器
- 配置内存层次结构
- 建立2D Mesh网络连接

#### 2. `configure_simulation(simulation_time, enable_statistics, output_filename)`
配置仿真参数：
- 设置仿真时间
- 配置统计收集
- 设置输出文件

#### 3. `set_workload_config(core_type, config)`
自定义特定核心类型的工作负载配置

#### 4. `get_system_info()`
获取系统配置信息

#### 5. `get_components()`
获取所有系统组件的引用

## 使用方法

### 方法1：基本使用（替换原始脚本）

```python
from miranda_cpu_mesh_system import MirandaCPUMeshSystem

# 创建与原始脚本相同的系统
mesh_system = MirandaCPUMeshSystem()
mesh_system.build_system()
mesh_system.configure_simulation()
```

### 方法2：自定义配置

```python
from miranda_cpu_mesh_system import MirandaCPUMeshSystem

# 创建自定义配置的系统
mesh_system = MirandaCPUMeshSystem(
    mesh_size_x=8,
    mesh_size_y=8,
    link_bandwidth="100GiB/s",
    cpu_clock="4.0GHz",
    cache_size="128KiB"
)

mesh_system.build_system()
mesh_system.configure_simulation(simulation_time="200us")
```

### 方法3：使用便利函数

```python
from miranda_cpu_mesh_system import build_and_configure_system

# 一步创建和配置系统
system = build_and_configure_system(
    mesh_size_x=6,
    mesh_size_y=4,
    simulation_time="150us",
    cpu_clock="3.0GHz"
)
```

### 方法4：自定义工作负载

```python
# 创建系统
mesh_system = MirandaCPUMeshSystem()

# 自定义计算核心工作负载
custom_config = {
    "generator": "miranda.GUPSGenerator",
    "max_reqs_cycle": "4",
    "params": {
        "count": "10000",
        "max_address": "2097152",
        "iterations": "200"
    },
    "description": "高性能计算核心"
}

mesh_system.set_workload_config("compute_core", custom_config)
mesh_system.build_system()
mesh_system.configure_simulation()
```

## 工作负载类型

系统支持四种核心类型，每种都有不同的工作负载配置：

1. **主控核心** (`master_core`): STREAM基准测试
2. **内存控制器** (`memory_controller`): 随机内存访问
3. **I/O核心** (`io_core`): 单流顺序访问
4. **计算核心** (`compute_core`): GUPS基准测试

## 文件说明

### 1. `miranda_cpu_mesh_system.py`
核心类文件，包含：
- `MirandaCPUMeshSystem` 主类
- 便利函数 `create_miranda_mesh_system()` 和 `build_and_configure_system()`
- 完整的文档字符串和类型提示

### 2. `cpu_mesh_miranda_class_based.py`
直接替换原始脚本的版本，保持相同的功能但使用类实现。

### 3. `example_usage.py`
详细的使用示例，包含：
- 基本使用方法
- 自定义工作负载配置
- 大规模系统配置
- 便利函数使用
- 最小化系统示例

## 优势

### 1. 模块化
- 清晰的方法分离
- 易于理解和维护
- 支持单元测试

### 2. 可配置性
- 所有参数都可以自定义
- 支持运行时配置修改
- 灵活的工作负载配置

### 3. 可复用性
- 可在多个项目中使用
- 支持不同规模的系统
- 便利函数简化使用

### 4. 扩展性
- 易于添加新功能
- 支持新的工作负载类型
- 可扩展到不同拓扑

### 5. 错误处理
- 参数验证
- 状态检查
- 清晰的错误消息

## 运行示例

在SST环境中运行：

```bash
# 运行基于类的版本（替换原始脚本）
sst cpu_mesh_miranda_class_based.py

# 运行示例脚本
sst example_usage.py
```

## 注意事项

1. **SST限制**: 在一个脚本中只能配置一个系统
2. **导入错误**: 在非SST环境中会出现 `import sst` 错误，这是正常的
3. **文件路径**: 确保输出目录存在且有写权限
4. **内存使用**: 大规模系统可能需要更多内存

## 未来扩展

可能的扩展方向：

1. **支持其他拓扑**: Ring、Torus、Fat-tree等
2. **更多工作负载**: 添加新的Miranda生成器
3. **动态配置**: 运行时修改系统参数
4. **性能优化**: 优化大规模系统构建
5. **可视化**: 添加系统拓扑可视化功能

## 总结

通过将原始脚本封装为类，我们获得了一个更加灵活、可维护和可复用的Miranda CPU Mesh系统实现。这个类不仅保持了原始功能，还提供了更好的抽象和扩展能力。
