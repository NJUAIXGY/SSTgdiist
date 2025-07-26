#!/usr/bin/env python3
"""
分析4x4 mesh网格仿真结果
"""
import csv
from collections import defaultdict

def analyze_mesh_stats():
    print("=== 4x4 Mesh 网格仿真结果分析 ===\n")
    
    # 读取统计数据
    try:
        with open('mesh_stats_final.csv', 'r') as f:
            reader = csv.DictReader(f)
            data = list(reader)
        
        # 清理列名中的空格
        cleaned_data = []
        for row in data:
            cleaned_row = {k.strip(): v for k, v in row.items()}
            cleaned_data.append(cleaned_row)
        data = cleaned_data
        
        print(f"总统计记录数: {len(data)}")
        if data:
            print(f"仿真时间: {data[0].get('SimTime', 'N/A')}")
        print()
        
        # 分析不同类型的统计
        stat_types = defaultdict(int)
        components = set()
        
        for row in data:
            stat_types[row['StatisticName']] += 1
            components.add(row['ComponentName'])
        
        print("收集的统计类型:")
        for stat, count in sorted(stat_types.items()):
            print(f"  - {stat}: {count} 条记录")
        print()
        
        # 分析组件
        router_count = len([comp for comp in components if comp.startswith('router_')])
        print(f"参与仿真的组件数量: {len(components)}")
        print(f"路由器数量: {router_count}")
        print("组件列表:")
        for comp in sorted(components):
            comp_stats = sum(1 for row in data if row['ComponentName'] == comp)
            print(f"  - {comp}: {comp_stats} 条统计记录")
        print()
        
        # 分析包传输统计
        send_packets = sum(int(row.get('Sum.u64', 0)) for row in data 
                          if row['StatisticName'] == 'send_packet_count')
        recv_packets = sum(int(row.get('Sum.u64', 0)) for row in data 
                          if row['StatisticName'] == 'recv_packet_count')
        
        print(f"总发送包数: {send_packets}")
        print(f"总接收包数: {recv_packets}")
        
        # 分析带宽使用
        total_bits = sum(int(row.get('Sum.u64', 0)) for row in data 
                        if row['StatisticName'] == 'send_bit_count')
        print(f"总传输比特数: {total_bits}")
        print(f"总传输字节数: {total_bits // 8}")
        
        # 分析端口使用
        ports_used = set()
        for row in data:
            if row.get('StatisticSubId', '').startswith('port'):
                ports_used.add(row['StatisticSubId'])
        
        print(f"\n使用的端口: {sorted(ports_used)}")
        
        print("\n=== 网格拓扑验证 ===")
        print("4x4 mesh 应该有:")
        print("- 16 个路由器节点")
        print("- 每个内部节点最多4个网络连接 + 1个本地连接")
        print("- 边缘节点连接数较少")
        print("- 总链路数: 横向链路 12 条 + 纵向链路 12 条 = 24 条双向链路")
        
        print(f"\n实际创建的路由器数量: {router_count}")
        
        if router_count == 16:
            print("✓ 路由器数量正确")
        else:
            print("✗ 路由器数量不正确")
            
    except FileNotFoundError:
        print("错误: 找不到 mesh_stats_final.csv 文件")
        print("请先运行仿真: sst test.py")
    except Exception as e:
        print(f"分析时出错: {e}")

if __name__ == "__main__":
    analyze_mesh_stats()
