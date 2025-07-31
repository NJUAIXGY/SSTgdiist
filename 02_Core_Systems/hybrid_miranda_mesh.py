#!/usr/bin/env python3
"""
融合系统: Miranda CPU Mesh + Simple Connect Test
结合miranda_cpu_mesh_system.py的节点层次结构和simple_connect_test.py的网络拓扑
"""

import random
import json
import csv
import time
import os
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

# 导入SST库
import sst


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
    memory_request: bool = False  # 是否为内存请求


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


class MirandaCPUNode:
    """
    融合的Miranda CPU节点
    结合了完整的CPU-cache-内存层次结构和网络路由功能
    """
    
    def __init__(self, x: int, y: int, mesh_size: int = 4, 
                 cpu_clock: str = "2.4GHz",
                 cache_size: str = "32KiB",
                 memory_size: str = "128MiB",
                 link_bandwidth: str = "40GiB/s",
                 link_latency: str = "50ps",
                 stats_manager=None,
                 verbose: bool = True):
        # 位置信息
        self.x = x
        self.y = y
        self.position = (x, y)
        self.mesh_size = mesh_size
        self.node_id = y * mesh_size + x
        
        # 系统参数
        self.cpu_clock = cpu_clock
        self.cache_size = cache_size
        self.memory_size = memory_size
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        self.verbose = verbose
        
        # 网络路由
        self.router = Router(x, y)
        self.stats_manager = stats_manager
        
        # 邻居节点连接 (用于网络拓扑)
        self.neighbors: Dict[Direction, Optional['MirandaCPUNode']] = {
            Direction.NORTH: None,
            Direction.SOUTH: None,
            Direction.EAST: None,
            Direction.WEST: None
        }
        
        # 数据包队列 (网络层)
        self.input_queue: List[Packet] = []
        self.output_queues: Dict[Direction, List[Packet]] = {
            direction: [] for direction in Direction
        }
        
        # SST组件 (CPU层次结构)
        self.cpu_core = None
        self.router_component = None
        self.l1_cache = None
        self.memory_controller = None
        
        # 统计信息 - 简化版本
        self.packets_sent = 0
        self.packets_received = 0
        
        # 工作负载配置
        self.workload_config = self._get_workload_config()
        
        # SST统计
        if self.stats_manager:
            self._setup_sst_statistics()
        
        # 初始化SST组件
        self._create_sst_components()
    
    def _get_workload_config(self) -> Dict[str, Any]:
        """根据节点位置确定工作负载配置"""
        # 根据节点类型确定工作负载
        if self.x == 0 and self.y == 0:
            return {
                "generator": "miranda.STREAMBenchGenerator",
                "max_reqs_cycle": "2",
                "params": {
                    "verbose": "1",
                    "n": "10000",
                    "operandwidth": "8",
                    "iterations": "100"
                },
                "description": "主控核心 - STREAM基准测试"
            }
        elif self.x == self.mesh_size - 1 and self.y == self.mesh_size - 1:
            return {
                "generator": "miranda.RandomGenerator",
                "max_reqs_cycle": "4",
                "params": {
                    "verbose": "1",
                    "count": "5000",
                    "max_address": "1048576",
                    "min_address": "0",
                    "length": "64"
                },
                "description": "内存控制器 - 随机访问模式"
            }
        elif self.x == 0 or self.x == self.mesh_size - 1 or self.y == 0 or self.y == self.mesh_size - 1:
            return {
                "generator": "miranda.SingleStreamGenerator",
                "max_reqs_cycle": "1",
                "params": {
                    "verbose": "1",
                    "count": "2000",
                    "start_a": "0",
                    "length": "32",
                    "stride": "32"
                },
                "description": "I/O核心 - 单流访问模式"
            }
        else:
            return {
                "generator": "miranda.GUPSGenerator",
                "max_reqs_cycle": "2",
                "params": {
                    "verbose": "1",
                    "count": "3000",
                    "max_address": "524288",
                    "min_address": "0",
                    "iterations": "50"
                },
                "description": "计算核心 - GUPS基准测试"
            }
    
    def _setup_sst_statistics(self):
        """设置SST统计 - 简化版本"""
        # 暂时禁用SST统计，仅使用内部计数器
        pass
    
    def _create_sst_components(self):
        """创建SST组件 - 简化版本，仅用于网络仿真"""
        # 暂时简化SST组件创建，专注于网络功能
        if self.verbose:
            print(f"  节点({self.x},{self.y}): {self.workload_config['description']} (网络仿真模式)")
        
        # 注意：在真实SST环境中，这里会创建实际的SST组件
        # 目前简化为网络层面的仿真
    
    def _create_memory_hierarchy(self):
        """创建内存层次结构 - 简化版本"""
        # 在简化模式下，仅记录内存层次结构的概念
        if self.verbose:
            print(f"    配置内存: L1缓存({self.cache_size}) + 本地内存({self.memory_size})")
        
        # 注意：在真实SST环境中，这里会创建实际的内存组件
    
    def connect_neighbor(self, direction: Direction, neighbor: 'MirandaCPUNode'):
        """连接邻居节点 (网络拓扑层面)"""
        self.neighbors[direction] = neighbor
        
        # 在简化模式下，仅建立逻辑连接
        if self.verbose:
            print(f"    连接: ({self.x},{self.y}) -> {direction.value} -> ({neighbor.x},{neighbor.y})")
    
    def _connect_sst_routers(self, direction: Direction, neighbor: 'MirandaCPUNode'):
        """连接SST路由器组件"""
        # 方向到端口的映射
        port_map = {
            Direction.EAST: "port0",
            Direction.WEST: "port1", 
            Direction.SOUTH: "port2",
            Direction.NORTH: "port3"
        }
        
        reverse_port_map = {
            Direction.EAST: "port1",
            Direction.WEST: "port0",
            Direction.SOUTH: "port3", 
            Direction.NORTH: "port2"
        }
        
        if direction in port_map:
            link_name = f"mesh_link_{self.x}_{self.y}_to_{neighbor.x}_{neighbor.y}"
            link = sst.Link(link_name)
            link.connect(
                (self.router_component, port_map[direction], self.link_latency),
                (neighbor.router_component, reverse_port_map[direction], self.link_latency)
            )
    
    def send_packet(self, destination: Tuple[int, int], data: str, packet_id: int, memory_request: bool = False):
        """发送数据包 - 简化版本"""
        packet = Packet(
            source=self.position,
            destination=destination,
            data=data,
            packet_id=packet_id,
            memory_request=memory_request
        )
        self.input_queue.append(packet)
        self.packets_sent += 1
        
        # 移除SST统计记录
        
        request_type = "内存请求" if memory_request else "数据包"
        print(f"节点({self.x},{self.y})发送{request_type}{packet_id}到({destination[0]},{destination[1]}): {data}")
    
    def process_packets(self):
        """处理数据包队列 - 简化版本"""
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
    
    def _route_packet(self, packet: Packet):
        """路由数据包 - 简化版本"""
        next_direction = self.router.route_packet(packet)
        
        if next_direction == Direction.LOCAL:
            # 到达目标节点
            self.packets_received += 1
            
            # 移除SST统计记录
            
            request_type = "内存请求" if packet.memory_request else "数据包"
            print(f"节点({self.x},{self.y})接收到{request_type}{packet.packet_id}: {packet.data} (跳数: {packet.hop_count})")
            
            # 如果是内存请求，可以触发内存层次结构的处理
            if packet.memory_request:
                self._handle_memory_request(packet)
        else:
            # 转发到下一跳
            self.output_queues[next_direction].append(packet)
            print(f"节点({self.x},{self.y})转发包{packet.packet_id}到{next_direction.value}方向")
    
    def _handle_memory_request(self, packet: Packet):
        """处理内存请求"""
        # 这里可以添加与SST内存层次结构的交互逻辑
        # 例如触发缓存访问、内存访问等
        if self.verbose:
            print(f"  节点({self.x},{self.y})处理内存请求: {packet.data}")
    
    def simulate_cpu_cycle(self):
        """模拟CPU周期 - 简化版本"""
        pass  # 移除CPU周期统计
    
    def get_node_info(self) -> Dict[str, Any]:
        """获取节点信息 - 简化版本"""
        return {
            "position": self.position,
            "node_id": self.node_id,
            "workload": self.workload_config["description"],
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received
        }


class HybridMirandaMesh:
    """
    混合Miranda Mesh系统
    结合Miranda CPU系统的节点架构和Simple Connect Test的网络拓扑
    """
    
    def __init__(self, 
                 mesh_size_x: int = 4,
                 mesh_size_y: int = 4,
                 cpu_clock: str = "2.4GHz",
                 cache_size: str = "32KiB",
                 memory_size: str = "128MiB",
                 link_bandwidth: str = "40GiB/s",
                 link_latency: str = "50ps",
                 enable_sst_stats: bool = True,
                 output_dir: str = "./statistics_output",
                 verbose: bool = True):
        
        self.mesh_size_x = mesh_size_x
        self.mesh_size_y = mesh_size_y
        self.total_nodes = mesh_size_x * mesh_size_y
        self.cpu_clock = cpu_clock
        self.cache_size = cache_size
        self.memory_size = memory_size
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        self.output_dir = output_dir
        self.verbose = verbose
        
        # 网络状态
        self.nodes: Dict[Tuple[int, int], MirandaCPUNode] = {}
        self.packet_counter = 0
        self.enable_sst_stats = enable_sst_stats
        
        # 初始化SST统计管理器 - 简化版本，不使用SST统计
        self.stats_manager = None
        
        # 构建系统
        self._create_topology()
        self._connect_nodes()
        
        if verbose:
            self._print_system_summary()
    
    def _create_topology(self):
        """创建混合拓扑 (Miranda CPU节点 + Simple Connect网络)"""
        if self.verbose:
            print("=== 创建混合Miranda-SimpleConnect拓扑 ===")
        
        for x in range(self.mesh_size_x):
            for y in range(self.mesh_size_y):
                node = MirandaCPUNode(
                    x=x, y=y, 
                    mesh_size=self.mesh_size_x,
                    cpu_clock=self.cpu_clock,
                    cache_size=self.cache_size,
                    memory_size=self.memory_size,
                    link_bandwidth=self.link_bandwidth,
                    link_latency=self.link_latency,
                    stats_manager=self.stats_manager,
                    verbose=self.verbose
                )
                self.nodes[(x, y)] = node
                if self.verbose:
                    print(f"创建混合节点({x},{y})")
    
    def _connect_nodes(self):
        """连接节点形成mesh拓扑 (使用Simple Connect的连接逻辑)"""
        if self.verbose:
            print("\n连接混合节点...")
        
        link_count = 0
        for x in range(self.mesh_size_x):
            for y in range(self.mesh_size_y):
                node = self.nodes[(x, y)]
                
                # 连接北邻居
                if y > 0:
                    north_neighbor = self.nodes[(x, y-1)]
                    node.connect_neighbor(Direction.NORTH, north_neighbor)
                    
                # 连接南邻居  
                if y < self.mesh_size_y - 1:
                    south_neighbor = self.nodes[(x, y+1)]
                    node.connect_neighbor(Direction.SOUTH, south_neighbor)
                    
                # 连接东邻居
                if x < self.mesh_size_x - 1:
                    east_neighbor = self.nodes[(x+1, y)]
                    node.connect_neighbor(Direction.EAST, east_neighbor)
                    link_count += 1
                    
                # 连接西邻居
                if x > 0:
                    west_neighbor = self.nodes[(x-1, y)]
                    node.connect_neighbor(Direction.WEST, west_neighbor)
        
        if self.verbose:
            print(f"节点连接完成! 创建了{link_count}条双向链路")
    
    def _print_system_summary(self):
        """打印系统总结"""
        print(f"\n=== 混合Miranda Mesh系统总结 ===")
        print(f"🏗️  系统架构:")
        print(f"   • 网格规模: {self.mesh_size_x}×{self.mesh_size_y} = {self.total_nodes} 个混合节点")
        print(f"   • 节点架构: Miranda CPU + L1缓存({self.cache_size}) + 本地内存({self.memory_size})")
        print(f"   • 网络拓扑: Simple Connect XY路由")
        print(f"   • 链路性能: {self.link_bandwidth} 带宽, {self.link_latency} 延迟")
        print(f"   • CPU频率: {self.cpu_clock}")
        
        print(f"\n🧠 节点工作负载分布:")
        for (x, y), node in self.nodes.items():
            print(f"   • 节点({x},{y}): {node.workload_config['description']}")
        
        print(f"\n🚀 混合系统构建完成!")
    
    def get_node(self, x: int, y: int) -> MirandaCPUNode:
        """获取指定坐标的节点"""
        return self.nodes.get((x, y))
    
    def send_message(self, src_x: int, src_y: int, dst_x: int, dst_y: int, message: str, memory_request: bool = False):
        """在两个节点间发送消息"""
        if (src_x, src_y) not in self.nodes or (dst_x, dst_y) not in self.nodes:
            print("错误: 源或目标节点不存在")
            return
            
        source_node = self.nodes[(src_x, src_y)]
        self.packet_counter += 1
        source_node.send_packet((dst_x, dst_y), message, self.packet_counter, memory_request)
    
    def simulate_step(self):
        """模拟一个时钟周期"""
        # 处理网络数据包
        for node in self.nodes.values():
            node.process_packets()
            node.simulate_cpu_cycle()
    
    def simulate(self, steps: int = 10):
        """运行网络模拟"""
        print(f"\n开始混合系统模拟 {steps} 个时钟周期...")
        for step in range(steps):
            print(f"\n--- 时钟周期 {step + 1} ---")
            self.simulate_step()
    
    def print_statistics(self):
        """打印网络统计信息 - 简化版本"""
        print("\n=== 混合系统统计信息 ===")
        total_sent = 0
        total_received = 0
        
        for (x, y), node in self.nodes.items():
            node_info = node.get_node_info()
            print(f"节点({x},{y}): 发送={node_info['packets_sent']}, 接收={node_info['packets_received']}")
            
            total_sent += node_info['packets_sent']
            total_received += node_info['packets_received']
        
        print(f"\n总计: 发送={total_sent}, 接收={total_received}")
        success_rate = (total_received / total_sent * 100) if total_sent > 0 else 0
        print(f"包传递成功率: {success_rate:.2f}%")
    
    def print_topology(self):
        """打印网络拓扑"""
        print(f"\n=== {self.mesh_size_x}x{self.mesh_size_y} 混合Mesh拓扑 ===")
        for y in range(self.mesh_size_y):
            row = ""
            for x in range(self.mesh_size_x):
                row += f"({x},{y})"
                if x < self.mesh_size_x - 1:
                    row += " -- "
            print(row)
            if y < self.mesh_size_y - 1:
                print("  |     " * self.mesh_size_x)
    
    def export_sst_statistics(self, output_dir=None):
        """导出统计数据到文件 - 简化版本"""
        if output_dir is None:
            output_dir = self.output_dir
        
        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # 收集内部统计数据
        stats_data = {}
        for (x, y), node in self.nodes.items():
            node_key = f"node_{x}_{y}"
            stats_data[f"{node_key}_packets_sent"] = {"value": node.packets_sent}
            stats_data[f"{node_key}_packets_received"] = {"value": node.packets_received}
        
        # 导出为JSON格式
        json_file = f"{output_dir}/hybrid_mesh_statistics_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)
        print(f"混合系统统计数据已导出到JSON文件: {json_file}")
        
        # 生成简化的统计报告
        self._generate_simple_report(stats_data, f"{output_dir}/hybrid_mesh_report_{timestamp}.txt")
    
    def _generate_simple_report(self, stats_data, report_file):
        """生成简化的统计报告"""
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=== 混合Miranda Mesh系统简化报告 ===\n")
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
            f.write("-" * 40 + "\n")
            for node, metrics in sorted(node_stats.items()):
                f.write(f"节点{node}:\n")
                for metric, value in metrics.items():
                    f.write(f"  {metric}: {value}\n")
                f.write("\n")
            
            # 系统级汇总
            total_sent = sum(metrics.get('packets_sent', 0) for metrics in node_stats.values())
            total_received = sum(metrics.get('packets_received', 0) for metrics in node_stats.values())
            
            f.write("系统级汇总:\n")
            f.write("-" * 40 + "\n")
            f.write(f"总发送包数: {total_sent}\n")
            f.write(f"总接收包数: {total_received}\n")
            success_rate = (total_received / total_sent * 100) if total_sent > 0 else 0
            f.write(f"包传递成功率: {success_rate:.2f}%\n")
        
        print(f"混合系统简化统计报告已生成: {report_file}")


def test_hybrid_mesh_communication():
    """测试混合mesh网络通信"""
    print("=== 混合Miranda Mesh网络通信测试 ===\n")
    
    # 创建混合mesh网络
    mesh = HybridMirandaMesh(
        mesh_size_x=4,
        mesh_size_y=4,
        enable_sst_stats=True,
        verbose=True
    )
    
    # 打印拓扑
    mesh.print_topology()
    
    print("\n=== 开始混合系统通信测试 ===")
    
    # 测试场景1: 普通数据通信
    print("\n1. 测试普通数据通信:")
    mesh.send_message(0, 0, 0, 1, "Hello from master core")
    mesh.send_message(1, 1, 2, 1, "Compute core communication")
    
    # 测试场景2: 内存请求通信
    print("\n2. 测试内存请求通信:")
    mesh.send_message(0, 0, 3, 3, "Memory request to corner", memory_request=True)
    mesh.send_message(1, 1, 3, 3, "Cache miss request", memory_request=True)
    
    # 测试场景3: 混合通信
    print("\n3. 测试混合通信:")
    mesh.send_message(0, 0, 2, 2, "Data to compute core")
    mesh.send_message(2, 2, 0, 0, "Result back to master", memory_request=True)
    
    # 运行模拟
    mesh.simulate(steps=10)
    
    # 打印统计信息
    mesh.print_statistics()
    
    # 导出SST统计数据
    print("\n=== 导出混合系统SST统计数据 ===")
    mesh.export_sst_statistics()
    
    return mesh


def test_hybrid_workload_patterns():
    """测试混合工作负载模式"""
    print("\n\n=== 混合工作负载模式测试 ===")
    
    mesh = HybridMirandaMesh(enable_sst_stats=True, verbose=True)
    
    print("\n进行工作负载特定的通信测试...")
    
    # 1. 主控核心分发任务
    print("\n1. 主控核心分发任务:")
    mesh.send_message(0, 0, 1, 1, "Task distribution to compute cores")
    mesh.send_message(0, 0, 2, 2, "Compute task assignment")
    
    # 2. 计算核心请求内存
    print("\n2. 计算核心请求内存:")
    mesh.send_message(1, 1, 3, 3, "Memory access request", memory_request=True)
    mesh.send_message(2, 2, 3, 3, "Cache miss to memory controller", memory_request=True)
    
    # 3. I/O核心数据流
    print("\n3. I/O核心数据流:")
    mesh.send_message(0, 1, 1, 2, "I/O data stream")
    mesh.send_message(3, 1, 2, 1, "I/O response data")
    
    # 4. 结果收集
    print("\n4. 结果收集:")
    mesh.send_message(1, 1, 0, 0, "Compute result to master")
    mesh.send_message(2, 2, 0, 0, "Processing complete notification")
    
    # 运行足够长的模拟
    mesh.simulate(steps=15)
    
    # 打印统计信息
    mesh.print_statistics()
    
    # 导出统计数据
    mesh.export_sst_statistics()
    
    return mesh


if __name__ == "__main__":
    # 运行混合系统通信测试
    test_hybrid_mesh_communication()
    
    # 运行混合工作负载测试
    test_hybrid_workload_patterns()
    
    print("\n=== 混合系统测试完成 ===")
