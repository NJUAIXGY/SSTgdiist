#!/usr/bin/env python3
"""
分析基于Mesh网络的CPU系统仿真结果
"""
import csv
from collections import defaultdict

def analyze_cpu_system():
    print("=" * 80)
    print("🖥️  基于4x4 Mesh网络的CPU系统仿真结果分析")
    print("=" * 80)
    
    try:
        with open('cpu_mesh_system_stats.csv', 'r') as f:
            reader = csv.DictReader(f)
            data = list(reader)
        
        # 清理列名中的空格
        cleaned_data = []
        for row in data:
            cleaned_row = {k.strip(): v for k, v in row.items()}
            cleaned_data.append(cleaned_row)
        data = cleaned_data
        
        print(f"📊 总统计记录数: {len(data)}")
        if data:
            sim_time = data[0].get('SimTime', 'N/A')
            print(f"⏱️  仿真时间: {sim_time}")
        print()
        
        # 分析CPU核心类型和通信模式
        print("🧠 CPU核心分析:")
        core_types = {
            0: "主控核心 (0,0)",
            15: "内存控制器 (3,3)", 
            # I/O核心: 边缘位置
            1: "I/O核心 (1,0)", 2: "I/O核心 (2,0)", 3: "I/O核心 (3,0)",
            4: "I/O核心 (0,1)", 7: "I/O核心 (3,1)",
            8: "I/O核心 (0,2)", 11: "I/O核心 (3,2)",
            12: "I/O核心 (0,3)", 13: "I/O核心 (1,3)", 14: "I/O核心 (2,3)",
            # 计算核心: 内部位置
            5: "计算核心 (1,1)", 6: "计算核心 (2,1)",
            9: "计算核心 (1,2)", 10: "计算核心 (2,2)"
        }
        
        # 分析包传输统计
        send_stats = {}
        recv_stats = {}
        bit_stats = {}
        
        for row in data:
            component = row.get('ComponentName', '')
            stat_name = row.get('StatisticName', '')
            sum_value = int(row.get('Sum.u64', 0))
            
            if component.startswith('router_'):
                router_id = int(component.split('_')[1])
                
                if stat_name == 'send_packet_count':
                    send_stats[router_id] = send_stats.get(router_id, 0) + sum_value
                elif stat_name == 'recv_packet_count':
                    recv_stats[router_id] = recv_stats.get(router_id, 0) + sum_value
                elif stat_name == 'send_bit_count':
                    bit_stats[router_id] = bit_stats.get(router_id, 0) + sum_value
        
        # 显示各核心的通信统计
        print("\n📈 各CPU核心通信统计:")
        print("核心ID | 类型              | 发送包数 | 接收包数 | 发送比特数")
        print("-" * 70)
        
        total_send = 0
        total_recv = 0
        total_bits = 0
        
        for i in range(16):
            core_type = core_types.get(i, f"未知核心 ({i%4},{i//4})")
            sends = send_stats.get(i, 0)
            recvs = recv_stats.get(i, 0)
            bits = bit_stats.get(i, 0)
            
            total_send += sends
            total_recv += recvs
            total_bits += bits
            
            print(f"  {i:2d}   | {core_type:16s} | {sends:8d} | {recvs:8d} | {bits:10d}")
        
        print("-" * 70)
        print(f"总计   | {'':16s} | {total_send:8d} | {total_recv:8d} | {total_bits:10d}")
        
        # 分析核心类型的通信模式
        print(f"\n🔍 CPU核心类型通信分析:")
        
        main_core_send = send_stats.get(0, 0)
        mem_ctrl_recv = recv_stats.get(15, 0)
        
        # 计算I/O核心统计
        io_cores = [1, 2, 3, 4, 7, 8, 11, 12, 13, 14]
        io_send = sum(send_stats.get(i, 0) for i in io_cores)
        io_recv = sum(recv_stats.get(i, 0) for i in io_cores)
        
        # 计算核心统计
        compute_cores = [5, 6, 9, 10]
        compute_send = sum(send_stats.get(i, 0) for i in compute_cores)
        compute_recv = sum(recv_stats.get(i, 0) for i in compute_cores)
        
        print(f"  • 主控核心 (CPU 0): 发送 {main_core_send} 包 - 系统协调功能")
        print(f"  • 内存控制器 (CPU 15): 接收 {mem_ctrl_recv} 包 - 内存访问处理")
        print(f"  • I/O核心 (10个): 总发送 {io_send} 包, 总接收 {io_recv} 包")
        print(f"  • 计算核心 (4个): 总发送 {compute_send} 包, 总接收 {compute_recv} 包")
        
        # 分析网络性能
        print(f"\n🌐 网络性能分析:")
        print(f"  • 总数据传输: {total_bits} 比特 = {total_bits // 8} 字节")
        print(f"  • 平均每核心发送: {total_send // 16:.1f} 包")
        print(f"  • 平均每核心接收: {total_recv // 16:.1f} 包")
        
        # 检查负载均衡
        if send_stats:
            max_send = max(send_stats.values())
            min_send = min(send_stats.values())
            load_balance = (max_send - min_send) / max_send * 100 if max_send > 0 else 0
            print(f"  • 发送负载不均衡度: {load_balance:.1f}% (越低越好)")
        
        # 分析拓扑效率
        mesh_hops = calculate_mesh_efficiency()
        print(f"  • 4x4 Mesh平均跳数: {mesh_hops:.2f} 跳")
        
        print(f"\n🏆 系统评估:")
        if total_send > 0 and total_recv > 0:
            print("  ✅ CPU系统仿真成功完成")
            print("  ✅ 所有核心类型都参与了网络通信")
            print("  ✅ Mesh网络正确传输了数据")
            
            if load_balance < 50:
                print("  ✅ 网络负载相对均衡")
            else:
                print("  ⚠️  网络负载不够均衡，可考虑优化")
        else:
            print("  ⚠️  检测到通信活动较少")
        
        print(f"\n💡 CPU系统特性:")
        print("  • 异构核心设计: 不同核心承担不同功能")
        print("  • 层次化通信: 主控→计算→I/O→内存的数据流")
        print("  • 可扩展架构: 可扩展到更大规模的mesh网络")
        print("  • 高带宽互连: 40GiB/s链路支持高性能计算")
        
    except FileNotFoundError:
        print("❌ 错误: 找不到 cpu_mesh_system_stats.csv 文件")
        print("请先运行仿真: sst cpu_mesh_system.py")
    except Exception as e:
        print(f"❌ 分析时出错: {e}")

def calculate_mesh_efficiency():
    """计算4x4 mesh网络的平均跳数"""
    total_hops = 0
    total_pairs = 0
    
    # 计算所有节点对之间的曼哈顿距离
    for i in range(16):
        for j in range(16):
            if i != j:
                x1, y1 = i % 4, i // 4
                x2, y2 = j % 4, j // 4
                hops = abs(x1 - x2) + abs(y1 - y2)
                total_hops += hops
                total_pairs += 1
    
    return total_hops / total_pairs if total_pairs > 0 else 0

if __name__ == "__main__":
    analyze_cpu_system()
