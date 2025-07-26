# 📊 Results Data Directory

## 仿真结果数据说明
此目录包含各种系统仿真运行产生的统计数据和结果文件。

## 文件分类

### 🎯 核心系统结果
- **simplified_miranda_stats.csv** - 简化Miranda系统统计数据
  - 16个CPU核心的性能指标
  - 网络路由器统计信息
  - 内存访问模式数据

### 🔬 实验系统结果
- **cpu_mesh_system_stats.csv** - CPU网格系统统计
- **enhanced_mesh_stats.csv** - 增强网格系统统计
- **force_traffic_mesh_stats.csv** - 强制流量网格统计
- **mesh_stats_final.csv** - 最终网格统计数据

### 🧪 测试系统结果
- **basic_mesh_stats.csv** - 基础网格测试统计
- **minimal_mesh_stats.csv** - 最小网格测试统计
- **simple_cpu_stats.csv** - 简单CPU测试统计

### 🔄 系统演进结果
- **active_cpu_stats.csv** - 活跃CPU系统统计
- **flowing_cpu_stats.csv** - 流动CPU系统统计

## 数据结构说明

### CPU统计指标
```
- cycles: CPU周期数
- reqs_issued: 发出的内存请求数
- reqs_returned: 返回的内存请求数
- IPC: 每周期指令数 (Instructions Per Cycle)
```

### 网络统计指标
```
- send_packet_count: 发送数据包计数
- recv_packet_count: 接收数据包计数
- router_latency: 路由器延迟
- link_utilization: 链路利用率
```

### 内存统计指标
```
- memory_requests: 内存请求总数
- cache_hits: 缓存命中次数
- cache_misses: 缓存未命中次数
- memory_bandwidth: 内存带宽利用率
```

## 分析工具

### 使用分析脚本
```bash
# 进入分析工具目录
cd ../04_Analysis_Tools/

# 分析特定结果文件
python analyze_results.py ../06_Results_Data/simplified_miranda_stats.csv
```

### 可视化数据
```bash
# 生成图表和可视化
python visualize_topology.py
python traffic_analysis.py
```

## 重要结果文件

### 🌟 推荐分析
**simplified_miranda_stats.csv** - 主要系统的完整统计数据
- 16个Miranda CPU核心的详细性能数据
- 完整的网络拓扑统计信息
- 多种工作负载的性能对比

### 📈 性能对比
通过对比不同配置的CSV文件，可以分析：
- 不同网格规模的性能影响
- 各种工作负载的效率差异
- 网络拓扑优化效果
- 内存系统配置影响

## 数据解读指南

### 性能指标
1. **CPU效率**: 查看cycles和reqs_returned比率
2. **网络性能**: 分析packet_count和latency
3. **内存效率**: 检查cache hit率和bandwidth
4. **系统平衡**: 对比各核心的负载分布

### 优化建议
- 根据统计数据调整配置参数
- 识别性能瓶颈和热点
- 优化工作负载分配策略
- 调整网络和内存配置

## 数据格式

### CSV文件结构
```
Component,Statistic,Value,Type,Units
cpu_0,cycles,1000000,Accumulator,cycles
router_0,send_packet_count,5000,Accumulator,packets
...
```

### 数据字段说明
- **Component**: 组件名称（cpu_X, router_X等）
- **Statistic**: 统计项名称
- **Value**: 统计值
- **Type**: 数据类型（Accumulator, Histogram等）
- **Units**: 单位（cycles, packets, bytes等）

## 注意事项

1. **文件大小**: 某些CSV文件可能较大，建议使用适当的工具处理
2. **数据精度**: 统计数据反映仿真精度，注意解读上下文
3. **版本对应**: 确保结果文件与对应的系统版本匹配
4. **备份重要**: 重要的实验结果建议备份保存

## 最后更新
2024年7月25日
