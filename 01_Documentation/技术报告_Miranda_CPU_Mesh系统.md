# Miranda CPU Mesh系统技术报告

**项目名称**: 基于SST框架的4x4 Miranda CPU Mesh网络系统  
**主要文件**: `cpu_mesh_miranda.py`, `cpu_mesh_simplified.py`, `cpu_mesh_dfs.py`  
**报告日期**: 2025年7月27日  
**版本**: v2.0

---

## 🎯 项目概述

### 项目目标
本项目旨在构建一个基于SST (Structural Simulation Toolkit) 框架的4x4网格拓扑CPU系统，使用Miranda CPU模拟器生成真实的指令级内存访问流量，实现高性能网络互连架构的仿真研究。

### 系统特点
- **真实CPU建模**: 使用Miranda BaseCPU进行指令级仿真
- **多样化系统**: 包含完整系统、简化系统和DFS算法模拟系统
- **分层工作负载**: 4种不同类型的基准测试工作负载
- **网络互连**: 高性能2D Mesh网络拓扑
- **内存层次**: 多级缓存和内存系统集成
- **统一数据管理**: 所有输出数据统一存放在专门目录中
- **性能分析**: 全面的统计数据收集和分析

### 系统版本
1. **cpu_mesh_miranda.py** - 完整版Miranda CPU网格系统
2. **cpu_mesh_simplified.py** - 简化版系统（推荐日常使用）
3. **cpu_mesh_dfs.py** - DFS深度优先搜索算法模拟系统

---

## 🏗️ 系统架构

### 总体架构图
```
┌─────────────────────────────────────────────────────────────────┐
│                  4x4 Miranda CPU Mesh系统架构                    │
├─────────────────────────────────────────────────────────────────┤
│  系统版本:   完整版 | 简化版 | DFS算法版                          │
│  CPU核心层:  16个Miranda BaseCPU + L1缓存                        │
│  网络层:     24条双向链路的2D Mesh拓扑                           │
│  内存层:     共享内存控制器 + 分布式缓存系统                       │
│  统计层:     全面的性能监控和数据收集                             │
│  数据层:     统一输出目录 (03_Output_Data/)                       │
└─────────────────────────────────────────────────────────────────┘
```

### 三个系统版本对比

| 特性 | 完整版 (miranda) | 简化版 (simplified) | DFS版 (dfs) |
|------|------------------|-------------------|-------------|
| CPU核心数量 | 16个 | 16个 | 16个 |
| 工作负载类型 | 4种分层负载 | 统一GUPS负载 | DFS遍历模拟 |
| 内存系统 | 完整层次结构 | 简化配置 | DFS优化配置 |
| 适用场景 | 完整性能研究 | 快速验证测试 | 图算法研究 |
| 复杂度 | 高 | 中 | 中 |
| 运行时间 | 较长 | 较短 | 中等 |

### 核心组件
1. **Miranda CPU核心**: 16个2.4GHz指令级CPU模拟器
2. **网络路由器**: 16个高性能hr_router组件  
3. **L1缓存系统**: 每核心32KiB L1缓存
4. **共享内存**: 2GiB统一地址空间内存控制器
5. **网络互连**: 40GiB/s带宽，50ps延迟链路

---

## 💻 Miranda CPU子系统

### CPU核心配置
| 参数 | 值 | 说明 |
|------|----|----- |
| 时钟频率 | 2.4GHz | 统一CPU时钟频率 |
| 缓存行大小 | 64字节 | 标准缓存行大小 |
| 最大待处理Load请求 | 16 | 内存并行度控制 |
| 最大待处理Store请求 | 16 | 写入并行度控制 |
| 最大待处理Custom请求 | 16 | 自定义操作并行度 |
| 重排序查找深度 | 16 | 乱序执行支持 |

### 工作负载分布策略

#### 1. 主控核心 (CPU 0, 位置: 0,0)
- **工作负载**: STREAM基准测试
- **功能**: 内存带宽密集型计算
- **配置参数**:
  ```python
  "generator": "miranda.STREAMBenchGenerator"
  "max_reqs_cycle": "2"
  "generatorParams.n": "10000"          # 数组大小
  "generatorParams.operandwidth": "8"   # 8字节操作数
  "generatorParams.iterations": "100"   # 迭代次数
  ```
- **特点**: 执行经典的STREAM基准测试，测量可持续内存带宽

#### 2. 内存控制器核心 (CPU 15, 位置: 3,3)
- **工作负载**: 随机内存访问
- **功能**: 模拟内存控制器行为
- **配置参数**:
  ```python
  "generator": "miranda.RandomGenerator"
  "max_reqs_cycle": "4"                 # 更高的处理能力
  "generatorParams.count": "5000"       # 请求数量
  "generatorParams.max_address": "1048576"  # 1MB地址空间
  "generatorParams.length": "64"        # 64字节请求
  ```
- **特点**: 高并发随机访问，模拟内存控制器工作模式

#### 3. I/O边缘核心 (边界节点)
- **工作负载**: 单流顺序访问
- **功能**: 模拟I/O设备和边缘计算
- **配置参数**:
  ```python
  "generator": "miranda.SingleStreamGenerator"
  "max_reqs_cycle": "1"                 # 较低的I/O频率
  "generatorParams.count": "2000"       # I/O操作数量
  "generatorParams.length": "32"        # 32字节I/O操作
  "generatorParams.stride": "32"        # 连续访问模式
  ```
- **特点**: 顺序访问模式，模拟典型I/O设备行为

#### 4. 计算核心 (内部节点)
- **工作负载**: GUPS基准测试
- **功能**: 随机访问性能测试
- **配置参数**:
  ```python
  "generator": "miranda.GUPSGenerator"
  "max_reqs_cycle": "2"
  "generatorParams.count": "3000"       # 请求数量
  "generatorParams.max_address": "524288"   # 512KB地址空间
  "generatorParams.iterations": "50"    # 迭代次数
  ```
- **特点**: GUPS (Giga Updates Per Second) 随机内存更新基准

---

## 🧠 DFS算法模拟子系统 (cpu_mesh_dfs.py)

### DFS系统概述
DFS (Depth-First Search) 算法模拟系统专门用于研究深度优先搜索算法在网格网络中的行为特征。

### DFS系统特点
- **算法导向**: 专门针对DFS算法的内存访问模式
- **网格遍历**: 模拟在4x4网格中的深度优先遍历
- **统一配置**: 所有CPU核心使用相同的DFS访问模式
- **优化连接**: 解决端口冲突的特殊连接配置

### DFS工作负载配置
```python
# DFS核心配置 - 所有核心统一使用
cpu_core.addParams({
    "verbose": "1",
    "printStats": "1", 
    "clock": "2.4GHz",
    "max_reqs_cycle": "2",
    # 使用GUPS生成器模拟DFS行为
    "generator": "miranda.GUPSGenerator",
    "generatorParams.verbose": "1",
    "generatorParams.count": "1000",        # DFS操作数量
    "generatorParams.max_address": "524288", # 512KB地址空间
    "generatorParams.min_address": "0",
})
```

### DFS系统技术要点
1. **端口冲突解决**: CPU 15的缓存连接改为port0，避免与内存控制器冲突
2. **统一访问模式**: 所有核心使用相同参数模拟DFS遍历行为
3. **网格拓扑利用**: 充分利用4x4网格结构特性
4. **专门输出**: 生成专门的DFS模拟统计数据

### DFS vs 传统算法对比
| 特性 | DFS模拟 | STREAM | GUPS | 随机访问 |
|------|---------|--------|------|----------|
| 访问模式 | 深度优先 | 顺序流 | 随机更新 | 完全随机 |
| 内存局部性 | 中等 | 高 | 低 | 低 |
| 网络流量 | 有向性 | 均匀 | 随机 | 随机 |
| 适用研究 | 图算法 | 带宽测试 | 延迟测试 | 通用性能 |

---

## 🔗 网络互连子系统

### 2D Mesh拓扑设计
- **网格规模**: 4×4 = 16节点
- **连接方式**: 东西南北四向连接
- **链路数量**: 24条双向高速链路
- **路由策略**: 维序路由 (Dimension-ordered routing)

### 网络性能参数
| 参数 | 值 | 说明 |
|------|----|----- |
| 链路带宽 | 40GiB/s | 高速互连带宽 |
| 链路延迟 | 50ps | 超低延迟设计 |
| Flit大小 | 8字节 | 网络传输单元 |
| 输入缓冲区 | 1KiB | 输入端缓存 |
| 输出缓冲区 | 1KiB | 输出端缓存 |
| 交叉开关带宽 | 40GiB/s | 内部交换带宽 |

### 路由器配置
```python
router = sst.Component(f"router_{i}", "merlin.hr_router")
router.addParams({
    "id": i,
    "num_ports": "5",           # 4个网络方向 + 1个本地端口
    "link_bw": "40GiB/s",
    "flit_size": "8B",
    "xbar_bw": "40GiB/s",
    "input_latency": "50ps",
    "output_latency": "50ps",
    "input_buf_size": "1KiB",
    "output_buf_size": "1KiB",
})
```

---

## 🧠 内存层次子系统

### L1缓存设计
每个CPU核心配备专用L1缓存，参数如下：

| 参数 | 值 | 说明 |
|------|----|----- |
| 缓存大小 | 32KiB | 每核心专用缓存 |
| 关联度 | 8路 | 组相联映射 |
| 访问延迟 | 1周期 | 超快缓存访问 |
| 替换策略 | LRU | 最近最少使用 |
| 一致性协议 | 无 | 简化设计 |
| 工作频率 | 2.4GHz | 与CPU同频 |

### 内存控制器系统
```python
memory_controller = sst.Component("memory_controller", "memHierarchy.MemController")
memory_controller.addParams({
    "clock": "1GHz",                    # 内存控制器频率
    "backing": "none",                  # 不使用文件后备
    "verbose": "0",                     # 日志级别
    "addr_range_start": "0",            # 地址空间起始
    "addr_range_end": "2147483647",     # 地址空间结束(2GB)
})
```

### 共享内存后端
```python
shared_memory = memory_controller.setSubComponent("backend", "memHierarchy.simpleMem")
shared_memory.addParams({
    "access_time": "100ns",             # 内存访问延迟
    "mem_size": "2GiB",                 # 总内存容量
})
```

---

## 🔌 组件互连架构

### CPU-缓存-网络连接
1. **CPU到L1缓存**: 通过standardInterface直接连接
2. **L1缓存到网络**: 通过MemNIC网络接口
3. **网络到共享内存**: 通过专用内存控制器

### 连接拓扑图
```
CPU_i ←→ L1Cache_i ←→ MemNIC_i ←→ Router_i ←→ Mesh网络
                                        ↓
                                  共享内存控制器
```

### 关键连接代码
```python
# CPU到L1缓存连接
cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
cpu_cache_link.connect(
    (mem_iface, "port", "50ps"),
    (l1_cache, "high_network_0", "50ps")
)

# L1缓存到网络连接
cache_router_link = sst.Link(f"cache_router_link_{i}")
cache_router_link.connect(
    (net_iface, "port", LINK_LATENCY),
    (router, "port4", LINK_LATENCY)
)
```

---

## 📊 性能监控与统计

### 统一输出数据管理
项目采用统一的数据输出管理策略：
- **输出目录**: `03_Output_Data/` 专门目录
- **文件格式**: CSV格式，便于数据分析
- **命名规范**: 系统名称_stats.csv

### 输出文件说明
| 文件名 | 对应系统 | 内容描述 |
|--------|----------|----------|
| `miranda_mesh_stats.csv` | 完整版系统 | 完整Miranda CPU网格系统统计 |
| `simplified_miranda_stats.csv` | 简化版系统 | 简化版系统性能数据 |
| `dfs_simulation_stats.csv` | DFS算法系统 | DFS算法模拟专门统计 |

### 统计数据收集策略
系统实现了多层次的性能统计收集：

#### 1. CPU层面统计
- **cycles**: CPU执行周期数
- **reqs_issued**: 发出的内存请求数
- **reqs_returned**: 完成的内存请求数

#### 2. 网络层面统计  
- **send_packet_count**: 发送数据包计数
- **recv_packet_count**: 接收数据包计数

#### 3. 内存层面统计
- **Cache统计**: 缓存命中率、缺失率等
- **MemController统计**: 内存访问延迟、带宽利用率等

### 统计配置示例
```python
# 统一输出配置
sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {
    "filepath": "../03_Output_Data/[系统名称]_stats.csv"
})

# 启用组件类型统计
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
```

---

## ⚙️ 关键技术实现

### 1. Miranda CPU集成
Miranda CPU模拟器提供指令级精确的CPU建模：
- **指令级仿真**: 真实的指令执行和内存访问模式
- **多种工作负载**: 支持STREAM、GUPS、随机访问等基准测试
- **内存接口**: 通过standardInterface与内存系统集成

### 2. 网络拓扑优化
- **维序路由**: 确定性路由减少死锁风险
- **高带宽设计**: 40GiB/s链路带宽满足高性能需求
- **低延迟优化**: 50ps链路延迟实现快速响应

### 3. 内存系统设计
- **分层缓存**: L1缓存提供快速局部访问
- **网络内存**: 通过网络访问共享内存空间
- **地址映射**: 统一2GB地址空间管理

### 4. 组件连接策略
解决了SST框架中的复杂连接问题：
- **端口命名标准化**: 使用新的端口命名规范
- **子组件集成**: 正确使用MemNIC网络接口
- **链路管理**: 避免端口冲突和连接错误

---

## 🔧 技术挑战与解决方案

### 挑战1: memHierarchy组件端口连接
**问题**: Cache组件不允许同时连接多个低级端口  
**解决方案**: 使用MemNIC子组件进行网络连接，避免直接端口冲突

### 挑战2: 地址空间映射
**问题**: 不同CPU核心的内存地址冲突  
**解决方案**: 使用统一的地址空间起始点(0)，通过内存控制器管理

### 挑战3: 网络组件集成
**问题**: merlin.endpoint组件不存在或端口不匹配  
**解决方案**: 使用MemNIC作为L1缓存的网络接口组件

### 挑战4: 工作负载配置
**问题**: 不同CPU核心需要不同的工作负载特性  
**解决方案**: 基于位置的条件配置，实现分层工作负载分配

---

## 📈 性能特征分析

### 理论性能指标
- **总CPU性能**: 16核 × 2.4GHz = 38.4 GIPS理论性能
- **网络带宽**: 24链路 × 40GiB/s = 960 GiB/s总带宽
- **内存容量**: 2GiB统一共享内存
- **缓存容量**: 16 × 32KiB = 512KiB总L1缓存

### 工作负载特性
1. **STREAM测试**: 测量可持续内存带宽性能
2. **GUPS测试**: 评估随机访问性能和延迟
3. **单流测试**: I/O设备顺序访问模式
4. **随机测试**: 内存控制器负载均衡能力

---

## 🚀 运行与验证

### 系统启动流程
1. **组件初始化**: 16个CPU核心和路由器创建
2. **网络构建**: 24条双向链路建立连接
3. **内存系统**: 共享内存控制器配置
4. **统计启用**: 性能监控系统激活
5. **仿真运行**: Miranda CPU开始执行工作负载

### 验证结果
- **成功启动**: 所有16个Miranda CPU核心正确初始化
- **网络连通**: 4x4 Mesh网络拓扑正确建立
- **工作负载运行**: 4种不同基准测试正常执行
- **仿真完成**: 系统完整运行977.59微秒

---

## 📝 使用指南

### 系统选择建议
1. **快速验证**: 使用简化版系统 (`cpu_mesh_simplified.py`)
2. **完整研究**: 使用完整版系统 (`cpu_mesh_miranda.py`)
3. **图算法研究**: 使用DFS版系统 (`cpu_mesh_dfs.py`)

### 运行命令
```bash
cd 02_Core_Systems/

# 简化版系统（推荐日常使用）
sst cpu_mesh_simplified.py

# 完整版系统（完整功能研究）
sst cpu_mesh_miranda.py

# DFS算法模拟系统（图算法研究）
sst cpu_mesh_dfs.py
```

### 输出文件位置
所有系统的输出文件统一存放在 `03_Output_Data/` 目录中：
```bash
# 查看输出结果
ls -la ../03_Output_Data/
cat ../03_Output_Data/simplified_miranda_stats.csv  # 简化版结果
cat ../03_Output_Data/miranda_mesh_stats.csv        # 完整版结果  
cat ../03_Output_Data/dfs_simulation_stats.csv      # DFS版结果
```

### 参数调优
可通过修改以下参数优化系统性能：

#### 通用参数
- `MESH_SIZE_X/Y`: 调整网格规模
- `LINK_BANDWIDTH`: 修改链路带宽 (默认: 40GiB/s)
- `LINK_LATENCY`: 调整网络延迟 (默认: 50ps)

#### 系统特定参数
**完整版系统**:
- CPU工作负载参数: 修改基准测试规模
- 内存层次参数: 调整缓存配置

**简化版系统**:
- GUPS生成器参数: 调整请求数量和地址空间

**DFS版系统**:
- DFS参数: 调整遍历深度和操作数量

---

## 🔮 扩展可能性

### 1. 规模扩展
- 支持更大规模的mesh网络 (8x8, 16x16等)
- 增加更多CPU核心和工作负载类型
- 实现更复杂的网络拓扑结构

### 2. 功能增强
- 添加L2/L3缓存层次
- 实现缓存一致性协议
- 集成更真实的内存模型

### 3. 性能优化
- 实现自适应路由算法
- 添加网络拥塞控制
- 优化内存访问调度策略

### 4. 分析工具
- 开发专用性能分析工具
- 实现可视化网络流量分析
- 添加实时性能监控界面

---

## 📚 技术参考

### SST框架组件
- **miranda.BaseCPU**: CPU模拟器核心组件
- **merlin.hr_router**: 高性能网络路由器
- **memHierarchy.Cache**: 缓存系统组件
- **memHierarchy.MemController**: 内存控制器

### 基准测试
- **STREAM**: 内存带宽基准测试
- **GUPS**: 随机访问性能测试  
- **SingleStream**: 顺序访问模式测试
- **Random**: 随机内存访问测试

### 网络技术
- **2D Mesh**: 二维网格拓扑结构
- **Dimension-ordered routing**: 维序路由算法
- **Flit-based switching**: 基于flit的包交换

---

## 📄 结论

本项目成功实现了一个基于SST框架的高性能4x4 Miranda CPU Mesh系统家族。该系统集合具有以下核心优势：

### 系统优势
1. **多样性**: 三个不同版本满足不同研究需求
   - 完整版: 全功能性能研究平台
   - 简化版: 快速验证和日常测试  
   - DFS版: 图算法专门研究平台

2. **真实性**: 使用Miranda CPU提供指令级精确建模

3. **完整性**: 集成了CPU、网络、内存的完整系统

4. **可扩展性**: 模块化设计支持灵活扩展

5. **可分析性**: 
   - 全面的性能统计和监控能力
   - 统一的数据输出管理
   - 标准化的CSV格式便于后续分析

### 应用场景
- **高性能计算架构研究**: 网络拓扑优化、内存系统设计
- **图算法性能分析**: DFS等图遍历算法的网络行为研究
- **基准测试平台**: STREAM、GUPS等标准基准的系统级评估
- **教育培训**: SST框架学习和CPU网格系统理解

### 数据管理创新
- **统一输出目录**: `03_Output_Data/` 目录集中管理所有模拟输出
- **标准化命名**: 清晰的文件命名规范便于识别和管理
- **版本化输出**: 不同系统版本生成独立的统计文件

该系统家族为高性能计算架构研究提供了有价值的仿真平台，可用于网络拓扑优化、内存系统设计、工作负载特征分析、图算法性能研究等多个研究方向。

---

**报告作者**: GitHub Copilot  
**技术支持**: SST Structural Simulation Toolkit  
**项目状态**: 完成并验证（包含三个系统版本）  
**最后更新**: 2025年7月27日
