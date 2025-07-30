#!/usr/bin/env python3
"""
4x4 Mesh网络实现
实现路由和拓扑，支持节点间通信
不包含内存和CPU实现
集成SST统计功能
"""

import random
import json
import csv
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# 尝试导入SST库，如果不可用则使用模拟版本
try:
    import sst
    SST_AVAILABLE = True
except ImportError:
    SST_AVAILABLE = False
    # 创建模拟的SST统计接口
    class MockSSTStatistics:
        def __init__(self):
            self.stats = {}
        
        def registerStatistic(self, name, description=""):
            self.stats[name] = {
                'name': name,
                'description': description,
                'value': 0,
                'events': []
            }
            return MockStatistic(name, self.stats)
        
        def getStatistics(self):
            return self.stats
    
    class MockStatistic:
        def __init__(self, name, stats_dict):
            self.name = name
            self.stats_dict = stats_dict
        
        def addData(self, value, time_stamp=None):
            if time_stamp is None:
                time_stamp = time.time()
            self.stats_dict[self.name]['value'] += value
            self.stats_dict[self.name]['events'].append({
                'value': value,
                'timestamp': time_stamp,
                'total': self.stats_dict[self.name]['value']
            })
    
    sst = MockSSTStatistics()


class Direction(Enum):
    """方向枚举"""
    NORTH = "north"
    SOUTH = "south" 
    EAST = "east"
    WEST = "west"
    LOCAL = "local"


@dataclass
class Packet:
    """数据包类"""
    source: Tuple[int, int]  # 源节点坐标
    destination: Tuple[int, int]  # 目标节点坐标
    data: str  # 数据内容
    packet_id: int  # 包ID
    hop_count: int = 0  # 跳数计数


class Router:
    """路由器类，实现XY路由算法"""
    
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.position = (x, y)
        
    def route_packet(self, packet: Packet) -> Direction:
        """
        使用XY路由算法计算下一跳方向
        先在X方向路由，再在Y方向路由
        """
        dest_x, dest_y = packet.destination
        
        # 已到达目标节点
        if dest_x == self.x and dest_y == self.y:
            return Direction.LOCAL
            
        # X方向路由优先
        if dest_x > self.x:
            return Direction.EAST
        elif dest_x < self.x:
            return Direction.WEST
        # X方向已对齐，Y方向路由
        elif dest_y > self.y:
            return Direction.SOUTH
        elif dest_y < self.y:
            return Direction.NORTH
        
        return Direction.LOCAL


class MeshNode:
    """Mesh网络节点"""
    
    def __init__(self, x: int, y: int, mesh_size: int = 4, stats_manager=None):
        self.x = x
        self.y = y
        self.position = (x, y)
        self.mesh_size = mesh_size
        self.router = Router(x, y)
        self.stats_manager = stats_manager
        
        # 邻居节点连接
        self.neighbors: Dict[Direction, Optional['MeshNode']] = {
            Direction.NORTH: None,
            Direction.SOUTH: None,
            Direction.EAST: None,
            Direction.WEST: None
        }
        
        # 数据包队列
        self.input_queue: List[Packet] = []
        self.output_queues: Dict[Direction, List[Packet]] = {
            direction: [] for direction in Direction
        }
        
        # 统计信息
        self.packets_sent = 0
        self.packets_received = 0
        self.packets_forwarded = 0
        
        # SST统计
        if self.stats_manager:
            self.sst_packets_sent = self.stats_manager.registerStatistic(
                f"node_{x}_{y}_packets_sent", 
                f"Total packets sent from node ({x},{y})"
            )
            self.sst_packets_received = self.stats_manager.registerStatistic(
                f"node_{x}_{y}_packets_received", 
                f"Total packets received by node ({x},{y})"
            )
            self.sst_packets_forwarded = self.stats_manager.registerStatistic(
                f"node_{x}_{y}_packets_forwarded", 
                f"Total packets forwarded by node ({x},{y})"
            )
            self.sst_hop_count = self.stats_manager.registerStatistic(
                f"node_{x}_{y}_hop_count", 
                f"Hop count for packets received by node ({x},{y})"
            )
            self.sst_queue_length = self.stats_manager.registerStatistic(
                f"node_{x}_{y}_queue_length", 
                f"Input queue length for node ({x},{y})"
            )
        
    def connect_neighbor(self, direction: Direction, neighbor: 'MeshNode'):
        """连接邻居节点"""
        self.neighbors[direction] = neighbor
        
    def send_packet(self, destination: Tuple[int, int], data: str, packet_id: int):
        """发送数据包"""
        packet = Packet(
            source=self.position,
            destination=destination,
            data=data,
            packet_id=packet_id
        )
        self.input_queue.append(packet)
        self.packets_sent += 1
        
        # SST统计记录
        if self.stats_manager:
            self.sst_packets_sent.addData(1)
            self.sst_queue_length.addData(len(self.input_queue))
            
        print(f"节点({self.x},{self.y})发送包{packet_id}到({destination[0]},{destination[1]}): {data}")
        
    def process_packets(self):
        """处理数据包队列"""
        # 处理输入队列中的数据包
        while self.input_queue:
            packet = self.input_queue.pop(0)
            self._route_packet(packet)
            
        # 转发输出队列中的数据包到邻居节点
        for direction, queue in self.output_queues.items():
            if queue and direction != Direction.LOCAL:
                neighbor = self.neighbors[direction]
                if neighbor:
                    packet = queue.pop(0)
                    neighbor.input_queue.append(packet)
                    packet.hop_count += 1
                    self.packets_forwarded += 1
                    
                    # SST统计记录
                    if self.stats_manager:
                        self.sst_packets_forwarded.addData(1)
                    
    def _route_packet(self, packet: Packet):
        """路由数据包"""
        next_direction = self.router.route_packet(packet)
        
        if next_direction == Direction.LOCAL:
            # 到达目标节点
            self.packets_received += 1
            
            # SST统计记录
            if self.stats_manager:
                self.sst_packets_received.addData(1)
                self.sst_hop_count.addData(packet.hop_count)
                
            print(f"节点({self.x},{self.y})接收到包{packet.packet_id}: {packet.data} (跳数: {packet.hop_count})")
        else:
            # 转发到下一跳
            self.output_queues[next_direction].append(packet)
            print(f"节点({self.x},{self.y})转发包{packet.packet_id}到{next_direction.value}方向")


class Mesh4x4:
    """4x4 Mesh网络"""
    
    def __init__(self, enable_sst_stats=True):
        self.size = 4
        self.nodes: Dict[Tuple[int, int], MeshNode] = {}
        self.packet_counter = 0
        self.enable_sst_stats = enable_sst_stats
        
        # 初始化SST统计管理器
        if enable_sst_stats:
            if SST_AVAILABLE:
                self.stats_manager = sst
            else:
                self.stats_manager = sst
        else:
            self.stats_manager = None
            
        self._create_topology()
        self._connect_nodes()
        
    def _create_topology(self):
        """创建4x4网格拓扑"""
        print("创建4x4 Mesh拓扑...")
        for x in range(self.size):
            for y in range(self.size):
                node = MeshNode(x, y, self.size, self.stats_manager)
                self.nodes[(x, y)] = node
                print(f"创建节点({x},{y})")
                
    def _connect_nodes(self):
        """连接节点形成mesh拓扑"""
        print("\n连接节点...")
        for x in range(self.size):
            for y in range(self.size):
                node = self.nodes[(x, y)]
                
                # 连接北邻居
                if y > 0:
                    north_neighbor = self.nodes[(x, y-1)]
                    node.connect_neighbor(Direction.NORTH, north_neighbor)
                    
                # 连接南邻居  
                if y < self.size - 1:
                    south_neighbor = self.nodes[(x, y+1)]
                    node.connect_neighbor(Direction.SOUTH, south_neighbor)
                    
                # 连接东邻居
                if x < self.size - 1:
                    east_neighbor = self.nodes[(x+1, y)]
                    node.connect_neighbor(Direction.EAST, east_neighbor)
                    
                # 连接西邻居
                if x > 0:
                    west_neighbor = self.nodes[(x-1, y)]
                    node.connect_neighbor(Direction.WEST, west_neighbor)
                    
        print("节点连接完成!")
        
    def get_node(self, x: int, y: int) -> MeshNode:
        """获取指定坐标的节点"""
        return self.nodes.get((x, y))
        
    def send_message(self, src_x: int, src_y: int, dst_x: int, dst_y: int, message: str):
        """在两个节点间发送消息"""
        if (src_x, src_y) not in self.nodes or (dst_x, dst_y) not in self.nodes:
            print("错误: 源或目标节点不存在")
            return
            
        source_node = self.nodes[(src_x, src_y)]
        self.packet_counter += 1
        source_node.send_packet((dst_x, dst_y), message, self.packet_counter)
        
    def simulate_step(self):
        """模拟一个时钟周期"""
        for node in self.nodes.values():
            node.process_packets()
            
    def simulate(self, steps: int = 10):
        """运行网络模拟"""
        print(f"\n开始模拟 {steps} 个时钟周期...")
        for step in range(steps):
            print(f"\n--- 时钟周期 {step + 1} ---")
            self.simulate_step()
            
    def print_statistics(self):
        """打印网络统计信息"""
        print("\n=== 网络统计信息 ===")
        total_sent = 0
        total_received = 0
        total_forwarded = 0
        
        for (x, y), node in self.nodes.items():
            print(f"节点({x},{y}): 发送={node.packets_sent}, 接收={node.packets_received}, 转发={node.packets_forwarded}")
            total_sent += node.packets_sent
            total_received += node.packets_received
            total_forwarded += node.packets_forwarded
            
        print(f"\n总计: 发送={total_sent}, 接收={total_received}, 转发={total_forwarded}")
        
    def print_topology(self):
        """打印网络拓扑"""
        print("\n=== 4x4 Mesh拓扑 ===")
        for y in range(self.size):
            row = ""
            for x in range(self.size):
                row += f"({x},{y})"
                if x < self.size - 1:
                    row += " -- "
            print(row)
            if y < self.size - 1:
                print("  |     " * self.size)
    
    def export_sst_statistics(self, output_dir="./statistics_output"):
        """导出SST统计数据到文件"""
        if not self.stats_manager:
            print("SST统计未启用，无法导出")
            return
            
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # 获取所有统计数据
        all_stats = self.stats_manager.getStatistics()
        
        # 导出为JSON格式
        json_file = f"{output_dir}/mesh_statistics_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(all_stats, f, indent=2, ensure_ascii=False)
        print(f"SST统计数据已导出到JSON文件: {json_file}")
        
        # 导出为CSV格式（汇总数据）
        csv_file = f"{output_dir}/mesh_statistics_summary_{timestamp}.csv"
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Statistic_Name', 'Description', 'Total_Value', 'Event_Count'])
            
            for stat_name, stat_data in all_stats.items():
                writer.writerow([
                    stat_name,
                    stat_data.get('description', ''),
                    stat_data.get('value', 0),
                    len(stat_data.get('events', []))
                ])
        print(f"SST统计汇总已导出到CSV文件: {csv_file}")
        
        # 导出详细事件数据
        events_file = f"{output_dir}/mesh_statistics_events_{timestamp}.csv"
        with open(events_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Statistic_Name', 'Timestamp', 'Value', 'Running_Total'])
            
            for stat_name, stat_data in all_stats.items():
                for event in stat_data.get('events', []):
                    writer.writerow([
                        stat_name,
                        event.get('timestamp', ''),
                        event.get('value', 0),
                        event.get('total', 0)
                    ])
        print(f"SST统计事件详情已导出到CSV文件: {events_file}")
        
        # 生成统计报告
        self._generate_statistics_report(all_stats, f"{output_dir}/mesh_statistics_report_{timestamp}.txt")
        
    def _generate_statistics_report(self, stats_data, report_file):
        """生成详细的统计报告"""
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=== 4x4 Mesh网络SST统计报告 ===\n")
            f.write(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # 按节点分组统计
            node_stats = {}
            for stat_name, stat_data in stats_data.items():
                if 'node_' in stat_name:
                    parts = stat_name.split('_')
                    if len(parts) >= 4:
                        node_key = f"({parts[1]},{parts[2]})"
                        metric = '_'.join(parts[3:])
                        
                        if node_key not in node_stats:
                            node_stats[node_key] = {}
                        node_stats[node_key][metric] = stat_data.get('value', 0)
            
            # 输出节点统计
            f.write("节点级统计:\n")
            f.write("-" * 60 + "\n")
            for node, metrics in sorted(node_stats.items()):
                f.write(f"节点{node}:\n")
                for metric, value in metrics.items():
                    f.write(f"  {metric}: {value}\n")
                f.write("\n")
            
            # 网络级汇总
            total_sent = sum(metrics.get('packets_sent', 0) for metrics in node_stats.values())
            total_received = sum(metrics.get('packets_received', 0) for metrics in node_stats.values())
            total_forwarded = sum(metrics.get('packets_forwarded', 0) for metrics in node_stats.values())
            total_hop_count = sum(metrics.get('hop_count', 0) for metrics in node_stats.values())
            
            f.write("网络级汇总:\n")
            f.write("-" * 60 + "\n")
            f.write(f"总发送包数: {total_sent}\n")
            f.write(f"总接收包数: {total_received}\n")
            f.write(f"总转发包数: {total_forwarded}\n")
            f.write(f"总跳数: {total_hop_count}\n")
            if total_received > 0:
                f.write(f"平均跳数: {total_hop_count / total_received:.2f}\n")
            f.write(f"包传递成功率: {(total_received / total_sent * 100) if total_sent > 0 else 0:.2f}%\n")
        
        print(f"SST统计报告已生成: {report_file}")


def test_mesh_communication():
    """测试mesh网络通信"""
    print("=== 4x4 Mesh网络通信测试 ===\n")
    
    # 创建mesh网络，启用SST统计
    mesh = Mesh4x4(enable_sst_stats=True)
    
    # 打印拓扑
    mesh.print_topology()
    
    print("\n=== 开始通信测试 ===")
    
    # 测试场景1: 相邻节点通信
    print("\n1. 测试相邻节点通信:")
    mesh.send_message(0, 0, 0, 1, "Hello from (0,0) to (0,1)")
    mesh.send_message(1, 1, 2, 1, "Hello from (1,1) to (2,1)")
    
    # 测试场景2: 对角线通信
    print("\n2. 测试对角线通信:")
    mesh.send_message(0, 0, 3, 3, "Diagonal message from corner to corner")
    mesh.send_message(3, 0, 0, 3, "Another diagonal message")
    
    # 测试场景3: 中心节点通信
    print("\n3. 测试中心节点通信:")
    mesh.send_message(1, 1, 2, 2, "Center to center communication")
    
    # 运行模拟
    mesh.simulate(steps=8)
    
    # 打印统计信息
    mesh.print_statistics()
    
    # 导出SST统计数据
    print("\n=== 导出SST统计数据 ===")
    mesh.export_sst_statistics()
    
    return mesh


def test_random_communication():
    """测试随机通信模式"""
    print("\n\n=== 随机通信测试 ===")
    
    mesh = Mesh4x4(enable_sst_stats=True)
    
    # 生成10个随机通信
    print("\n生成随机通信...")
    for i in range(10):
        src_x, src_y = random.randint(0, 3), random.randint(0, 3)
        dst_x, dst_y = random.randint(0, 3), random.randint(0, 3)
        
        # 避免自己给自己发消息
        while (src_x, src_y) == (dst_x, dst_y):
            dst_x, dst_y = random.randint(0, 3), random.randint(0, 3)
            
        message = f"Random message {i+1}"
        mesh.send_message(src_x, src_y, dst_x, dst_y, message)
    
    # 运行模拟
    mesh.simulate(steps=12)
    
    # 打印统计信息
    mesh.print_statistics()
    
    # 导出SST统计数据
    print("\n=== 导出随机测试SST统计数据 ===")
    mesh.export_sst_statistics()


def test_with_sst_statistics_demo():
    """演示SST统计功能的专用测试"""
    print("\n\n=== SST统计功能演示 ===")
    
    mesh = Mesh4x4(enable_sst_stats=True)
    
    print("\n进行多样化通信测试以生成丰富的统计数据...")
    
    # 1. 短距离通信
    mesh.send_message(0, 0, 0, 1, "Short distance 1")
    mesh.send_message(1, 0, 1, 1, "Short distance 2")
    
    # 2. 中距离通信
    mesh.send_message(0, 0, 2, 2, "Medium distance 1")
    mesh.send_message(1, 1, 3, 1, "Medium distance 2")
    
    # 3. 长距离通信
    mesh.send_message(0, 0, 3, 3, "Long distance 1")
    mesh.send_message(3, 0, 0, 3, "Long distance 2")
    
    # 4. 多个源到同一目标
    mesh.send_message(0, 0, 2, 2, "Multi-source 1")
    mesh.send_message(1, 1, 2, 2, "Multi-source 2")
    mesh.send_message(3, 3, 2, 2, "Multi-source 3")
    
    # 运行足够长的模拟
    mesh.simulate(steps=15)
    
    # 打印基本统计
    mesh.print_statistics()
    
    # 导出详细的SST统计数据
    print("\n=== 导出详细SST统计数据 ===")
    mesh.export_sst_statistics()
    
    return mesh


if __name__ == "__main__":
    # 运行基本通信测试
    test_mesh_communication()
    
    # 运行随机通信测试
    test_random_communication()
    
    # 运行SST统计功能演示
    test_with_sst_statistics_demo()
    
    print("\n=== 测试完成 ===")
