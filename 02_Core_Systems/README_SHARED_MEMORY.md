# 共享内存NoC架构实现说明

## 概述

本次更新实现了基于共享内存地址空间的NoC（片上网络）通信模型，允许任意节点间进行通信。与原来每个节点独立的内存系统不同，新架构通过网络连接的共享内存实现了真正的跨节点通信。

## 核心技术改进

### 1. 架构变更

**原架构（独立内存）:**
```
CPU -> L1缓存 -> 本地内存控制器 (128MB独立)
```

**新架构（共享内存）:**
```
CPU -> L1缓存 -> MemNIC -> 路由器 -> 网络 -> 共享内存控制器 (512MB共享)
```

### 2. 关键组件更新

#### NoCNode类的主要改进：

1. **节点类型区分**：
   - `is_memory_node`: 标识内存节点或计算节点
   - 内存节点：只包含共享内存控制器
   - 计算节点：包含CPU + L1缓存 + 网络接口

2. **网络接口（MemNIC）**：
   - 使用 `memHierarchy.MemNIC` 组件
   - 将内存请求打包成网络消息
   - 支持跨节点的内存访问

3. **共享内存系统**：
   - 512MB总地址空间
   - 分布在多个内存节点上
   - 支持地址范围分区

#### NoCMesh类的主要改进：

1. **内存节点管理**：
   - 默认四个角落节点作为内存节点
   - 可自定义内存节点位置
   - 自动配置地址映射

2. **工作负载优化**：
   - 跨节点内存访问模式
   - 基于节点位置的差异化负载
   - 分布式计算模拟

## 通信模式

### 1. 地址映射策略

- **总地址空间**: 512MB (0x00000000 - 0x1FFFFFFF)
- **分区方式**: 按内存节点数量平均分配
- **路由策略**: 基于地址的XY路由

### 2. 工作负载类型

1. **主控核心** (0,0)：
   - STREAM基准测试
   - 跨节点数据访问

2. **分布式访问核心** (右下角)：
   - 远程随机访问
   - 访问其他节点内存区域

3. **边界通信核心** (边界节点)：
   - 相邻节点访问
   - 单流访问模式

4. **分布式计算核心** (中心节点)：
   - 多节点GUPS测试
   - 跨多个内存区域访问

## 使用示例

```python
from noc_node_class import NoCMesh

# 创建4x4共享内存mesh网络
mesh = NoCMesh(
    mesh_size_x=4, 
    mesh_size_y=4,
    memory_nodes=[0, 3, 12, 15]  # 角落节点作为内存节点
)

# 启用统计收集
mesh.enable_all_statistics()
mesh.setup_statistics_output("shared_memory_stats.csv")

# 打印系统配置
mesh.print_summary()

# 创建通信演示
mesh.create_communication_demo()
```

## 预期性能表现

### 1. 网络流量特征
- **包数量**: 10K-50K 网络包
- **平均跳数**: 1-3 跳
- **缓存命中率**: 20-40% (跨节点访问)

### 2. 通信延迟
- **本地访问**: ~50ps (L1缓存命中)
- **远程访问**: ~200-500ps (网络 + 内存)
- **网络延迟**: 50ps × 跳数

### 3. 带宽利用
- **链路带宽**: 40GiB/s
- **预计利用率**: 5-15%
- **热点链路**: 内存节点周围

## 文件结构

```
02_Core_Systems/
├── noc_node_class.py              # 更新的NoC节点类
├── shared_memory_mesh_demo.py     # 共享内存演示脚本
└── README_SHARED_MEMORY.md        # 本文档
```

## 运行方法

```bash
# 进入核心系统目录
cd 02_Core_Systems/

# 运行共享内存演示
sst shared_memory_mesh_demo.py

# 查看统计结果
ls -la /home/anarchy/SST/sst_output_data/
```

## 技术要点

### 1. MemNIC配置
```python
# L1缓存网络接口
self.mem_nic = self.l1_cache.setSubComponent("memlink", "memHierarchy.MemNIC")
self.mem_nic.addParams({
    "group": "1",  # 计算节点组
    "network_bw": self.link_bandwidth,
    "min_packet_size": "8B",
    "max_packet_size": "64B",
})
```

### 2. 网络连接
```python
# 连接MemNIC到路由器
self.cache_network_link = sst.Link(f"cache_network_link_{self.node_id}")
self.cache_network_link.connect(
    (self.mem_nic, "port", "20ns"),
    (self.router, "port4", "20ns")  # 本地端口
)
```

### 3. 地址范围配置
```python
# 内存控制器地址范围
self.mem_ctrl.addParams({
    "addr_range_start": str(start_addr),
    "addr_range_end": str(end_addr),
})
```

## 调试建议

1. **检查网络连通性**: 确保MemNIC正确连接到路由器
2. **验证地址映射**: 检查内存地址范围是否正确分配
3. **监控网络统计**: 观察包发送/接收计数
4. **分析缓存性能**: 查看跨节点访问的缓存命中率

## 下一步扩展

1. **动态负载均衡**: 基于网络拥塞的路由优化
2. **缓存一致性**: 实现分布式缓存协议
3. **消息传递**: 基于内存映射的消息队列
4. **性能建模**: 详细的延迟和带宽分析
