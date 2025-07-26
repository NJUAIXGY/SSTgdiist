#!/usr/bin/env python3
"""
分析有网络流量的CPU系统结果
"""
import csv
from collections import defaultdict

def analyze_active_cpu_system():
    print("=" * 80)
    print("🔥 有实际网络流量的4x4 Mesh CPU系统分析")
    print("=" * 80)
    
    try:
        with open('active_cpu_stats.csv', 'r') as f:
            reader = csv.DictReader(f)
            data = list(reader)
        
        # 清理列名
        cleaned_data = []
        for row in data:
            cleaned_row = {k.strip(): v for k, v in row.items()}
            cleaned_data.append(cleaned_row)
        data = cleaned_data
        
        print(f"📊 统计记录数: {len(data)}")
        print(f"⏱️  仿真时间: {data[0].get('SimTime', 'N/A') if data else 'N/A'}")
        
        # 分析网络流量
        router_stats = defaultdict(lambda: {'send': 0, 'recv': 0, 'bits': 0})
        nic_stats = defaultdict(lambda: {'send': 0, 'recv': 0})
        
        for row in data:
            component = row.get('ComponentName', '')
            stat_name = row.get('StatisticName', '')
            sum_value = int(row.get('Sum.u64', 0))
            
            if component.startswith('router_'):
                router_id = int(component.split('_')[1])
                if stat_name == 'send_packet_count':
                    router_stats[router_id]['send'] += sum_value
                elif stat_name == 'recv_packet_count':
                    router_stats[router_id]['recv'] += sum_value
                elif stat_name == 'send_bit_count':
                    router_stats[router_id]['bits'] += sum_value
            
            elif 'test_nic' in component or 'nic' in stat_name.lower():
                # 尝试提取NIC统计
                if 'send' in stat_name.lower():
                    nic_id = hash(component) % 16  # 简单的ID提取
                    nic_stats[nic_id]['send'] += sum_value
                elif 'recv' in stat_name.lower():
                    nic_id = hash(component) % 16
                    nic_stats[nic_id]['recv'] += sum_value
        
        # 显示结果
        print(f"\n📈 路由器流量统计:")
        print("路由器ID | 发送包数 | 接收包数 | 发送比特数 | 状态")
        print("-" * 60)
        
        total_send = 0
        total_recv = 0
        total_bits = 0
        active_routers = 0
        
        for i in range(16):
            sends = router_stats[i]['send']
            recvs = router_stats[i]['recv']
            bits = router_stats[i]['bits']
            
            total_send += sends
            total_recv += recvs
            total_bits += bits
            
            if sends > 0 or recvs > 0:
                active_routers += 1
                status = "🟢 活跃"
            else:
                status = "🔴 空闲"
            
            print(f"    {i:2d}   | {sends:8d} | {recvs:8d} | {bits:10d} | {status}")
        
        print("-" * 60)
        print(f"   总计  | {total_send:8d} | {total_recv:8d} | {total_bits:10d} |")
        
        # 分析结果
        print(f"\n🔍 流量分析:")
        print(f"  • 总发送包数: {total_send}")
        print(f"  • 总接收包数: {total_recv}")
        print(f"  • 总传输比特: {total_bits} ({total_bits // 8} 字节)")
        print(f"  • 活跃路由器: {active_routers}/16")
        
        if total_send > 0:
            print(f"  • 平均每路由器发送: {total_send / 16:.1f} 包")
            print(f"  • 平均每路由器接收: {total_recv / 16:.1f} 包")
            
            # 检查负载分布
            if router_stats:
                send_values = [router_stats[i]['send'] for i in range(16)]
                max_send = max(send_values)
                min_send = min(send_values)
                if max_send > 0:
                    load_imbalance = (max_send - min_send) / max_send * 100
                    print(f"  • 负载不均衡度: {load_imbalance:.1f}%")
        
        # 评估结果
        print(f"\n🏆 系统评估:")
        if total_send > 0 and total_recv > 0:
            print("  ✅ 成功生成网络流量！")
            print("  ✅ Mesh网络正常工作")
            print("  ✅ CPU核心间通信建立")
            
            if active_routers >= 8:
                print("  ✅ 大部分路由器参与通信")
            else:
                print("  ⚠️  只有部分路由器活跃")
                
            if total_bits > 1000:
                print("  ✅ 产生了显著的数据传输")
            else:
                print("  ⚠️  数据传输量较少")
        else:
            print("  ❌ 仍然没有检测到网络流量")
            print("  💡 可能需要调整test_nic参数")
        
        # 提供改进建议
        if total_send == 0:
            print(f"\n💡 故障排除建议:")
            print("  1. 检查test_nic参数设置")
            print("  2. 验证路由器端口连接")
            print("  3. 确认统计收集配置")
            print("  4. 查看SST版本兼容性")
        else:
            print(f"\n🎉 网络流量修复成功！")
            print(f"  • 检测到 {total_send} 个发送包")
            print(f"  • 检测到 {total_recv} 个接收包")
            print(f"  • 传输了 {total_bits // 8} 字节数据")
        
    except FileNotFoundError:
        print("❌ 错误: 找不到 active_cpu_stats.csv 文件")
        print("请先运行: sst active_cpu_system.py")
    except Exception as e:
        print(f"❌ 分析出错: {e}")

if __name__ == "__main__":
    analyze_active_cpu_system()
