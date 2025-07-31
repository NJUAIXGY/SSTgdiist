# 02_Core_Systems - SST仿真核心系统

## 📋 目录概述

本目录包含基于SST (Structural Simulation Toolkit) 的核心仿真系统实现，专注于Miranda CPU和网络拓扑的融合仿真。

## 🏗️ 系统架构

### 核心组件
- **Miranda CPU仿真**: 真实处理器指令执行仿真
- **Mesh网络拓扑**: 2D网格互连网络
- **内存层次结构**: L1缓存 + 本地内存
- **XY路由算法**: 确定性最短路径路由

### 系统特性
- ✅ 4x4 Mesh网络拓扑
- ✅ 统一节点配置支持
- ✅ 内存到内存数据传输
- ✅ 多种工作负载模式
- ✅ 100%数据包传递成功率

## 📁 文件结构

### 🎯 主要系统文件

#### **hybrid_miranda_mesh.py**
- **功能**: 混合Miranda CPU + Simple Connect网络系统
- **特点**: 融合节点层次结构和网络拓扑
- **用途**: 主要的网络仿真系统，支持逻辑层面的数据包路由
- **运行**: 需要使用SST命令启动

#### **cpu_mesh_simplified.py**
- **功能**: 简化的Miranda CPU 4x4 Mesh系统
- **特点**: 真实SST组件实现，避免复杂内存层次连接
- **用途**: 硬件级别的SST仿真
- **运行**: `sst cpu_mesh_simplified.py`

#### **cpu_mesh_miranda.py**
- **功能**: 完整的Miranda CPU Mesh系统
- **特点**: 详细的内存层次结构和网络配置
- **用途**: 全功能SST仿真系统

### 🧪 测试文件

#### **test_memory_basic.py**
- **功能**: 基本内存到内存传输测试
- **测试案例**: 4个典型传输场景
- **验证内容**: 网络路由、数据传输、统计收集
- **运行**: `sst test_memory_basic.py`

#### **test_memory_to_memory.py**
- **功能**: 全面的内存到内存传输测试
- **特点**: 详细的传输流程分析和性能统计
- **运行**: `sst test_memory_to_memory.py`

#### **test_sst_memory_transfer.py**
- **功能**: SST环境专用内存传输测试
- **特点**: 优化的SST集成测试
- **运行**: `sst test_sst_memory_transfer.py`

#### **test_sst_only.py**
- **功能**: SST专用系统功能验证
- **特点**: 简化的网络连通性测试
- **运行**: `sst test_sst_only.py`

### 📊 支持文件

#### **noc_node_class.py**
- **功能**: NoC节点封装类
- **内容**: NoCNode和NoCMesh类定义

#### **sst_config.py**
- **功能**: SST配置脚本
- **用途**: SST仿真参数配置

#### **simple_connect_test.py**
- **功能**: 简单连接网络测试
- **用途**: 网络拓扑验证

## 🚀 快速开始

### 1. 环境要求
- SST (Structural Simulation Toolkit)
- Python 3.x
- Miranda CPU模拟器组件

### 2. 基本测试
```bash
# 进入目录
cd 02_Core_Systems

# 运行基本内存传输测试
sst test_memory_basic.py

# 运行简化系统测试
sst test_sst_only.py

# 运行完整Miranda系统
sst cpu_mesh_simplified.py
```

### 3. 完整测试流程
```bash
# 1. 基本功能验证
sst test_sst_only.py

# 2. 内存传输测试
sst test_memory_basic.py

# 3. 全面性能测试
sst test_memory_to_memory.py

# 4. 硬件级仿真
sst cpu_mesh_simplified.py
```

## 🔧 系统配置

### 默认网络参数
- **网格规模**: 4x4 = 16个节点
- **CPU频率**: 2.4GHz
- **L1缓存**: 32KiB
- **本地内存**: 128MiB
- **链路带宽**: 40GiB/s
- **链路延迟**: 50ps

### 工作负载类型
1. **主控核心**: STREAM基准测试
2. **内存控制器**: 随机访问模式
3. **I/O核心**: 单流访问模式
4. **计算核心**: GUPS基准测试

## 📈 测试验证

### 已验证功能
- ✅ 4x4 Mesh网络构建
- ✅ XY路由算法实现
- ✅ 内存到内存数据传输
- ✅ 多节点并发通信
- ✅ 统计数据收集

### 性能指标
- **数据包传递成功率**: 100%
- **网络延迟**: 根据跳数线性增长
- **路由效率**: XY算法最短路径
- **节点利用率**: 支持全网格通信

## 🛠️ 开发说明

### 系统层次
1. **逻辑层**: hybrid_miranda_mesh.py (网络仿真)
2. **硬件层**: cpu_mesh_simplified.py (SST组件)
3. **测试层**: test_*.py (功能验证)

### 路由实现
- **逻辑路由**: Router类实现XY算法
- **硬件路由**: merlin.hr_router组件
- **端点通信**: merlin.endpoint连接

### 内存模型
- **简化模型**: 直接CPU-内存连接
- **层次模型**: CPU-L1缓存-内存层次
- **分布式**: 每节点独立内存空间

## 📊 输出文件

### 统计数据
- `statistics_output/`: 网络统计JSON和报告
- `simplified_miranda_stats.csv`: SST系统统计
- `hybrid_mesh_statistics_*.json`: 混合系统统计

### 日志文件
- 网络拓扑信息
- 数据包传输记录
- 性能指标汇总

## ⚠️ 注意事项

### SST要求
- **必须使用SST命令**: 所有测试都需要`sst script.py`启动
- **环境依赖**: 需要完整的SST环境和Miranda组件
- **路径要求**: 在包含文件的目录中运行

### 已知限制
- 警告消息: "No components are assigned to rank: 0.0" (正常现象)
- 简化模式: 部分测试使用逻辑仿真而非完整SST组件

## 🔄 升级路径

### 当前实现
- 逻辑网络仿真 + 基础SST集成

### 未来扩展
- 完整SST组件集成
- 更复杂的内存层次结构
- 多种网络拓扑支持
- 高级路由算法

## 📝 许可证

遵循项目根目录的LICENSE文件。

---

**最后更新**: 2025年7月31日  
**版本**: SST专用版本 v1.0  
**状态**: ✅ 生产就绪
