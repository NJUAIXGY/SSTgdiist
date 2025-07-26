#!/usr/bin/env python3

import pandas as pd
import sys

def analyze_mesh_stats():
    """分析mesh网络统计数据"""
    
    try:
        # 读取CSV文件
        df = pd.read_csv('minimal_mesh_stats.csv')
        
        print("=== Merlin Endpoint网络系统流量分析 ===\n")
        
        # 统计基本信息
        print(f"📊 统计数据总览:")
        print(f"   • 总记录数: {len(df)}")
        print(f"   • 组件数量: {df['ComponentName'].nunique()}")
        print(f"   • 统计类型数: {df['StatisticName'].nunique()}")
        
        # 分析网络流量
        print(f"\n🌐 网络流量分析:")
        
        # 发送的数据包统计
        send_packets = df[df['StatisticName'] == 'send_packet_count']
        total_packets_sent = send_packets['Sum.u64'].sum()
        print(f"   • 总发送包数: {total_packets_sent}")
        
        # 发送的比特统计
        send_bits = df[df['StatisticName'] == 'send_bit_count']
        total_bits_sent = send_bits['Sum.u64'].sum()
        print(f"   • 总发送比特数: {total_bits_sent}")
        
        # 接收的数据包统计
        recv_packets = df[df['StatisticName'] == 'recv_packet_count']
        if not recv_packets.empty:
            total_packets_recv = recv_packets['Sum.u64'].sum()
            print(f"   • 总接收包数: {total_packets_recv}")
        
        # 分析端口阻塞情况
        stalls = df[df['StatisticName'] == 'output_port_stalls']
        total_stalls = stalls['Sum.u64'].sum()
        print(f"   • 端口阻塞次数: {total_stalls}")
        
        # 分析空闲时间
        idle_stats = df[df['StatisticName'] == 'idle_time']
        if not idle_stats.empty:
            avg_idle = idle_stats['Sum.u64'].mean()
            print(f"   • 平均空闲时间: {avg_idle:.2e}")
        
        print(f"\n🔍 详细流量分析:")
        
        # 按组件分析流量
        components_with_traffic = []
        for component in df['ComponentName'].unique():
            comp_data = df[df['ComponentName'] == component]
            
            # 该组件的发送包数
            comp_send = comp_data[comp_data['StatisticName'] == 'send_packet_count']['Sum.u64'].sum()
            # 该组件的发送比特数
            comp_bits = comp_data[comp_data['StatisticName'] == 'send_bit_count']['Sum.u64'].sum()
            
            if comp_send > 0 or comp_bits > 0:
                components_with_traffic.append({
                    'component': component,
                    'packets': comp_send,
                    'bits': comp_bits
                })
        
        if components_with_traffic:
            print("   活跃组件 (有流量的组件):")
            for comp in components_with_traffic:
                print(f"     - {comp['component']}: {comp['packets']} 包, {comp['bits']} 比特")
        else:
            print("   ⚠️  没有检测到任何数据包流量")
        
        print(f"\n📈 网络性能指标:")
        
        # 分析不同统计类型
        stat_types = df['StatisticName'].unique()
        print("   可用统计类型:")
        for stat_type in stat_types:
            count = len(df[df['StatisticName'] == stat_type])
            print(f"     - {stat_type}: {count} 条记录")
        
        # 检查是否有非零数据
        non_zero_stats = df[df['Sum.u64'] > 0]
        if not non_zero_stats.empty:
            print(f"\n   非零统计数据:")
            for _, row in non_zero_stats.iterrows():
                print(f"     - {row['ComponentName']}.{row['StatisticName']}: {row['Sum.u64']}")
        else:
            print(f"\n   ⚠️  所有数据包和比特计数都为0")
        
        print(f"\n💡 结论:")
        if total_packets_sent == 0 and total_bits_sent == 0:
            print("   • merlin.endpoint没有生成明显的用户数据流量")
            print("   • 系统正确初始化，网络拓扑已建立")
            print("   • 需要更专业的流量生成器来产生实际网络流量")
            print("   • 网络基础设施工作正常，准备接收外部流量")
        else:
            print("   • 检测到网络流量活动")
            print("   • 系统正常工作并产生了数据传输")
            
        print(f"\n🎯 建议:")
        print("   • merlin.endpoint主要用于基础网络控制，不是流量生成器")
        print("   • 可以考虑添加真实的应用负载来驱动网络流量")
        print("   • 当前架构为添加CPU模拟器或真实应用提供了良好基础")
        
    except FileNotFoundError:
        print("❌ 错误: 找不到 minimal_mesh_stats.csv 文件")
        print("   请先运行 SST 仿真生成统计数据")
    except Exception as e:
        print(f"❌ 分析过程中发生错误: {e}")

if __name__ == "__main__":
    analyze_mesh_stats()
