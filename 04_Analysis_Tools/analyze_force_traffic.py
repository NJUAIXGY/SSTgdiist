import pandas as pd
import numpy as np

print("=== 分析强制流量生成系统的网络统计 ===")
print()

# 读取强制流量统计数据
try:
    df = pd.read_csv("force_traffic_mesh_stats.csv")
    print(f"✅ 成功读取统计数据: {len(df)} 条记录")
    print(f"📊 统计项目: {list(df.columns)}")
    print()
    
    # 分析数据包流量
    packet_stats = df[df['Statistic'].str.contains('packet_count', na=False)]
    if not packet_stats.empty:
        print("🚀 数据包流量分析:")
        print("-" * 50)
        
        send_stats = packet_stats[packet_stats['Statistic'] == 'send_packet_count']
        recv_stats = packet_stats[packet_stats['Statistic'] == 'recv_packet_count']
        
        if not send_stats.empty:
            total_sent = send_stats['Sum'].sum()
            avg_sent = send_stats['Sum'].mean()
            print(f"📤 总发送包数: {int(total_sent):,}")
            print(f"📤 平均每节点发送: {avg_sent:.1f} 包")
            print(f"📤 发送包数范围: {send_stats['Sum'].min():.0f} - {send_stats['Sum'].max():.0f}")
        
        if not recv_stats.empty:
            total_recv = recv_stats['Sum'].sum()
            avg_recv = recv_stats['Sum'].mean()
            print(f"📥 总接收包数: {int(total_recv):,}")
            print(f"📥 平均每节点接收: {avg_recv:.1f} 包")
            print(f"📥 接收包数范围: {recv_stats['Sum'].min():.0f} - {recv_stats['Sum'].max():.0f}")
        
        # 流量成功率
        if not send_stats.empty and not recv_stats.empty:
            success_rate = (total_recv / total_sent) * 100 if total_sent > 0 else 0
            print(f"✅ 流量传输成功率: {success_rate:.1f}%")
    
    print()
    
    # 分析比特流量
    bit_stats = df[df['Statistic'].str.contains('bit_count', na=False)]
    if not bit_stats.empty:
        print("💾 比特流量分析:")
        print("-" * 50)
        
        send_bits = bit_stats[bit_stats['Statistic'] == 'send_bit_count']
        recv_bits = bit_stats[bit_stats['Statistic'] == 'recv_bit_count']
        
        if not send_bits.empty:
            total_sent_bits = send_bits['Sum'].sum()
            print(f"📤 总发送比特数: {int(total_sent_bits):,} bits")
            print(f"📤 总发送数据量: {total_sent_bits / (8 * 1024):.2f} KB")
        
        if not recv_bits.empty:
            total_recv_bits = recv_bits['Sum'].sum()
            print(f"📥 总接收比特数: {int(total_recv_bits):,} bits")
            print(f"📥 总接收数据量: {total_recv_bits / (8 * 1024):.2f} KB")
    
    print()
    
    # 分析延迟性能
    latency_stats = df[df['Statistic'].str.contains('latency', na=False)]
    if not latency_stats.empty:
        print("⏱️ 网络延迟分析:")
        print("-" * 50)
        avg_latency = latency_stats['Mean'].mean()
        min_latency = latency_stats['Min'].min()
        max_latency = latency_stats['Max'].max()
        print(f"⏱️ 平均延迟: {avg_latency:.2f}")
        print(f"⏱️ 最小延迟: {min_latency:.2f}")
        print(f"⏱️ 最大延迟: {max_latency:.2f}")
    
    print()
    
    # 分析缓冲区占用
    buffer_stats = df[df['Statistic'].str.contains('occupancy', na=False)]
    if not buffer_stats.empty:
        print("🔄 缓冲区使用分析:")
        print("-" * 50)
        avg_occupancy = buffer_stats['Mean'].mean()
        max_occupancy = buffer_stats['Max'].max()
        print(f"🔄 平均缓冲区占用: {avg_occupancy:.2f}")
        print(f"🔄 最大缓冲区占用: {max_occupancy:.2f}")
    
    print()
    
    # 节点级详细分析
    print("🔍 各节点流量详情:")
    print("-" * 50)
    
    for node_id in range(16):  # 4x4 = 16 个节点
        node_send = df[(df['Component'].str.contains(f'router_{node_id}')) & 
                      (df['Statistic'] == 'send_packet_count')]
        node_recv = df[(df['Component'].str.contains(f'router_{node_id}')) & 
                      (df['Statistic'] == 'recv_packet_count')]
        
        send_count = node_send['Sum'].iloc[0] if not node_send.empty else 0
        recv_count = node_recv['Sum'].iloc[0] if not node_recv.empty else 0
        
        target = (node_id + 1) % 16
        print(f"节点 {node_id:2d} -> 节点 {target:2d}: 发送 {send_count:4.0f} 包, 接收 {recv_count:4.0f} 包")
    
    print()
    print("🎉 流量生成成功分析完成！")
    
    # 成功总结
    if not packet_stats.empty:
        total_traffic = send_stats['Sum'].sum() if not send_stats.empty else 0
        if total_traffic > 0:
            print(f"✅ 网络流量生成成功: 共传输 {int(total_traffic):,} 个数据包")
            print("✅ 问题已解决: 使用强制参数配置成功生成了网络流量")
        else:
            print("❌ 仍未检测到流量，需要进一步调试")
    
except Exception as e:
    print(f"❌ 读取统计文件时出错: {e}")
    print("请检查 force_traffic_mesh_stats.csv 文件是否存在且格式正确")
