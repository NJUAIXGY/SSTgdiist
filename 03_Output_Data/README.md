# 输出数据目录

这个目录用于存放所有SST模拟脚本生成的输出数据文件。

## 文件说明

### CSV统计文件
- `dfs_simulation_stats.csv` - DFS算法模拟的统计数据
- `simplified_miranda_stats.csv` - 简化Miranda CPU系统的统计数据  
- `miranda_mesh_stats.csv` - 完整Miranda CPU网格系统的统计数据

### 统计数据包含内容
- CPU核心性能指标（周期数、请求数等）
- 网络路由器统计（包传输计数等）
- 内存层次结构性能数据
- 缓存和内存控制器统计

## 使用方法

1. 运行SST脚本后，对应的CSV文件会自动生成在此目录中
2. 可以使用Excel、Python pandas或其他数据分析工具打开CSV文件进行分析
3. 建议定期备份重要的模拟结果数据

## 注意事项

- 每次运行相同的SST脚本会覆盖之前的输出文件
- 如需保留历史数据，请在运行前手动重命名或备份现有文件
- CSV文件采用UTF-8编码，包含详细的性能统计信息
