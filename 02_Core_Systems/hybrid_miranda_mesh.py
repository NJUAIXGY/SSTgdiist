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
    size_bytes: int = 64  # 数据包大小(字节)
    timestamp: float = 0.0  # 发送时间戳
    creation_time: float = 0.0  # 创建时间


class LogicalRouter:
    """逻辑路由器类，实现XY路由算法 (用于逻辑层面的数据包路由)"""
    
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
        
        # 网络路由 - 分离逻辑路由和SST组件
        self.logical_router = LogicalRouter(x, y)  # 逻辑层面的路由算法
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
        
        # SST组件 (真实的硬件组件)
        self.cpu_core = None
        self.sst_router = None  # SST merlin.hr_router 组件
        self.l1_cache = None
        self.memory_controller = None
        self.endpoint = None  # SST 端点组件
        
        # 统计信息 - 详细网络流量统计
        self.packets_sent = 0
        self.packets_received = 0
        self.packets_forwarded = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.bytes_forwarded = 0
        
        # 按方向统计流量
        self.traffic_by_direction = {
            Direction.NORTH: {"packets": 0, "bytes": 0},
            Direction.SOUTH: {"packets": 0, "bytes": 0},
            Direction.EAST: {"packets": 0, "bytes": 0},
            Direction.WEST: {"packets": 0, "bytes": 0},
            Direction.LOCAL: {"packets": 0, "bytes": 0}
        }
        
        # 按消息类型统计
        self.traffic_by_type = {
            "data": {"packets": 0, "bytes": 0},
            "memory_request": {"packets": 0, "bytes": 0}
        }
        
        # 延迟统计
        self.packet_latencies = []
        self.total_hop_count = 0
        
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
        """创建SST组件 - 使用实际的merlin.hr_router (修正端口协议)"""
        if self.verbose:
            print(f"  节点({self.x},{self.y}): 创建SST组件 - {self.workload_config['description']}")
        
        # 生成唯一的组件名称，避免重复
        import time
        timestamp = str(int(time.time() * 1000000))[-6:]  # 使用微秒时间戳后6位
        router_name = f"router_{self.node_id}_{timestamp}"
        
        # 创建SST路由器组件 (merlin.hr_router)
        self.sst_router = sst.Component(router_name, "merlin.hr_router")
        self.sst_router.addParams({
            "id": self.node_id,
            "num_ports": "5",  # 4个网络方向 + 1个本地端口 (按照标准配置)
            "link_bw": self.link_bandwidth,
            "flit_size": "8B",
            "xbar_bw": self.link_bandwidth,
            "input_latency": self.link_latency,
            "output_latency": self.link_latency,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 配置mesh拓扑子组件
        topo_sub = self.sst_router.setSubComponent("topology", "merlin.mesh")
        topo_sub.addParams({
            "network_name": "Hybrid_Miranda_Mesh",
            "shape": f"{self.mesh_size}x{self.mesh_size}",
            "width": "1x1",
            "local_ports": "1",
        })
        
        # 创建独立的端点组件 (使用test_nic代替merlin.endpoint)
        endpoint_name = f"endpoint_{self.node_id}_{timestamp}"
        self.endpoint = sst.Component(endpoint_name, "merlin.test_nic")
        self.endpoint.addParams({
            "id": self.node_id,
            "num_peers": str(self.mesh_size * self.mesh_size),
            "num_messages": "10",
            "message_size": "64B",
        })
        
        # 为test_nic设置networkIF子组件
        self.netif = self.endpoint.setSubComponent("networkIF", "merlin.linkcontrol")
        self.netif.addParams({
            "link_bw": self.link_bandwidth,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 连接端点到路由器的本地端口 (port4)
        local_link_name = f"local_link_{self.node_id}_{timestamp}"
        local_link = sst.Link(local_link_name)
        local_link.connect(
            (self.sst_router, "port4", self.link_latency),  # 路由器本地端口
            (self.netif, "rtr_port", self.link_latency)     # 网络接口路由器端口
        )
        
        # 创建Miranda CPU核心 (如果需要)
        self._create_miranda_cpu()
        
        if self.verbose:
            print(f"    SST路由器创建完成: {router_name} (5端口配置 + 独立端点)")
            print(f"    端点连接完成: {endpoint_name} -> port4 (通过networkIF)")
    
    def _create_miranda_cpu(self):
        """创建Miranda CPU组件 (可选)"""
        # 根据需要创建实际的Miranda CPU组件
        # 目前保持简化，专注于网络部分
        if self.verbose:
            print(f"    Miranda CPU配置: {self.workload_config['description']}")
        
        # 在真实SST环境中，这里会创建实际的CPU组件
        # self.cpu_core = sst.Component(f"cpu_{self.node_id}", "miranda.BaseCPU")
        # self.cpu_core.addParams(self.workload_config["params"])
    
    def _create_memory_hierarchy(self):
        """创建内存层次结构 - 简化版本"""
        # 在简化模式下，仅记录内存层次结构的概念
        if self.verbose:
            print(f"    配置内存: L1缓存({self.cache_size}) + 本地内存({self.memory_size})")
        
        # 注意：在真实SST环境中，这里会创建实际的内存组件
    
    def connect_neighbor(self, direction: Direction, neighbor: 'MirandaCPUNode'):
        """连接邻居节点 (包含逻辑拓扑和SST组件连接)"""
        # 逻辑层面的连接
        self.neighbors[direction] = neighbor
        
        # SST组件层面的连接
        if self.sst_router and neighbor.sst_router:
            self._connect_sst_routers(direction, neighbor)
        
        if self.verbose:
            print(f"    连接: ({self.x},{self.y}) -> {direction.value} -> ({neighbor.x},{neighbor.y})")
    
    def _connect_sst_routers(self, direction: Direction, neighbor: 'MirandaCPUNode'):
        """连接SST路由器组件 - 标准5端口mesh配置"""
        # 标准的4端口mesh配置 (port0-3: 东西南北, port4: 本地)
        port_map = {
            Direction.EAST: "port0",   # 东
            Direction.WEST: "port1",   # 西
            Direction.SOUTH: "port2",  # 南
            Direction.NORTH: "port3",  # 北
            # port4 用于本地端点连接
        }
        
        reverse_port_map = {
            Direction.EAST: "port1",   # 东->西
            Direction.WEST: "port0",   # 西->东
            Direction.SOUTH: "port3",  # 南->北
            Direction.NORTH: "port2",  # 北->南
        }
        
        if direction in port_map:
            # 生成唯一的链路名称，避免重复
            import time
            timestamp = str(int(time.time() * 1000000))[-6:]
            link_name = f"mesh_link_{self.x}_{self.y}_to_{neighbor.x}_{neighbor.y}_{timestamp}"
            link = sst.Link(link_name)
            
            # 连接两个路由器的对应端口
            link.connect(
                (self.sst_router, port_map[direction], self.link_latency),
                (neighbor.sst_router, reverse_port_map[direction], self.link_latency)
            )
            
            if self.verbose:
                print(f"      SST链路: {port_map[direction]} <-> {reverse_port_map[direction]} ({link_name})")
        else:
            if self.verbose:
                print(f"      警告: 未知方向 {direction}")
    
    def get_sst_router(self):
        """获取SST路由器组件引用"""
        return self.sst_router
    
    def get_endpoint(self):
        """获取SST端点组件引用"""
        return self.endpoint
    
    def send_packet(self, destination: Tuple[int, int], data: str, packet_id: int, memory_request: bool = False, size_bytes: int = 64):
        """发送数据包 - 带流量统计"""
        import time
        current_time = time.time()
        
        packet = Packet(
            source=self.position,
            destination=destination,
            data=data,
            packet_id=packet_id,
            memory_request=memory_request,
            size_bytes=size_bytes,
            timestamp=current_time,
            creation_time=current_time
        )
        self.input_queue.append(packet)
        
        # 更新发送统计
        self.packets_sent += 1
        self.bytes_sent += size_bytes
        
        # 按类型统计
        packet_type = "memory_request" if memory_request else "data"
        self.traffic_by_type[packet_type]["packets"] += 1
        self.traffic_by_type[packet_type]["bytes"] += size_bytes
        
        request_type = "内存请求" if memory_request else "数据包"
        if self.verbose:
            print(f"节点({self.x},{self.y})发送{request_type}{packet_id}到({destination[0]},{destination[1]}): {data} ({size_bytes}字节)")
    
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
        """路由数据包 - 使用逻辑路由器进行路由决策，包含流量统计"""
        next_direction = self.logical_router.route_packet(packet)
        
        if next_direction == Direction.LOCAL:
            # 到达目标节点
            import time
            arrival_time = time.time()
            latency = arrival_time - packet.creation_time
            
            # 更新接收统计
            self.packets_received += 1
            self.bytes_received += packet.size_bytes
            self.packet_latencies.append(latency)
            self.total_hop_count += packet.hop_count
            
            # 按方向统计
            self.traffic_by_direction[Direction.LOCAL]["packets"] += 1
            self.traffic_by_direction[Direction.LOCAL]["bytes"] += packet.size_bytes
            
            request_type = "内存请求" if packet.memory_request else "数据包"
            if self.verbose:
                print(f"节点({self.x},{self.y})接收到{request_type}{packet.packet_id}: {packet.data} (跳数: {packet.hop_count}, 延迟: {latency*1000:.2f}ms, {packet.size_bytes}字节)")
            
            # 如果是内存请求，可以触发内存层次结构的处理
            if packet.memory_request:
                self._handle_memory_request(packet)
        else:
            # 转发到下一跳
            self.output_queues[next_direction].append(packet)
            
            # 更新转发统计
            self.packets_forwarded += 1
            self.bytes_forwarded += packet.size_bytes
            
            # 按方向统计转发流量
            self.traffic_by_direction[next_direction]["packets"] += 1
            self.traffic_by_direction[next_direction]["bytes"] += packet.size_bytes
            
            if self.verbose:
                print(f"节点({self.x},{self.y})转发包{packet.packet_id}到{next_direction.value}方向 ({packet.size_bytes}字节)")
    
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
        """获取节点信息 - 包含详细流量统计"""
        avg_latency = sum(self.packet_latencies) / len(self.packet_latencies) if self.packet_latencies else 0
        avg_hop_count = self.total_hop_count / self.packets_received if self.packets_received > 0 else 0
        
        return {
            "position": self.position,
            "node_id": self.node_id,
            "workload": self.workload_config["description"],
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "packets_forwarded": self.packets_forwarded,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "bytes_forwarded": self.bytes_forwarded,
            "total_packets": self.packets_sent + self.packets_received + self.packets_forwarded,
            "total_bytes": self.bytes_sent + self.bytes_received + self.bytes_forwarded,
            "avg_latency_ms": avg_latency * 1000,
            "avg_hop_count": avg_hop_count,
            "traffic_by_direction": self.traffic_by_direction.copy(),
            "traffic_by_type": self.traffic_by_type.copy()
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
        """创建混合拓扑 (Miranda CPU节点 + SST merlin.hr_router 网络)"""
        if self.verbose:
            print("=== 创建混合Miranda-SST Merlin拓扑 ===")
        
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
                    print(f"创建混合节点({x},{y}) - SST路由器ID: {node.node_id}")
    
    def _connect_nodes(self):
        """连接节点形成mesh拓扑 (使用SST merlin.hr_router进行实际连接)"""
        if self.verbose:
            print("\n连接SST路由器节点...")
        
        link_count = 0
        for x in range(self.mesh_size_x):
            for y in range(self.mesh_size_y):
                node = self.nodes[(x, y)]
                
                # 只连接南邻居和东邻居，避免重复连接
                # 连接东邻居
                if x < self.mesh_size_x - 1:
                    east_neighbor = self.nodes[(x+1, y)]
                    node.connect_neighbor(Direction.EAST, east_neighbor)
                    link_count += 1
                    
                # 连接南邻居  
                if y < self.mesh_size_y - 1:
                    south_neighbor = self.nodes[(x, y+1)]
                    node.connect_neighbor(Direction.SOUTH, south_neighbor)
                    link_count += 1
                
                # 设置反向引用(逻辑层面，不创建SST链路)
                # 连接北邻居 (仅逻辑引用)
                if y > 0:
                    north_neighbor = self.nodes[(x, y-1)]
                    self.nodes[(x, y)].neighbors[Direction.NORTH] = north_neighbor
                    
                # 连接西邻居 (仅逻辑引用)
                if x > 0:
                    west_neighbor = self.nodes[(x-1, y)]
                    self.nodes[(x, y)].neighbors[Direction.WEST] = west_neighbor
        
        if self.verbose:
            print(f"SST路由器连接完成! 创建了{link_count}条双向链路，使用merlin.hr_router")
    
    def _print_system_summary(self):
        """打印系统总结"""
        print(f"\n=== 混合Miranda Mesh系统总结 (SST版本) ===")
        print(f"🏗️  系统架构:")
        print(f"   • 网格规模: {self.mesh_size_x}×{self.mesh_size_y} = {self.total_nodes} 个混合节点")
        print(f"   • 节点架构: Miranda CPU + L1缓存({self.cache_size}) + 本地内存({self.memory_size})")
        print(f"   • 网络拓扑: SST merlin.hr_router (标准5端口配置)")
        print(f"   • 路由算法: XY维序路由 (逻辑层) + merlin mesh拓扑 (SST层)")
        print(f"   • 链路性能: {self.link_bandwidth} 带宽, {self.link_latency} 延迟")
        print(f"   • CPU频率: {self.cpu_clock}")
        
        print(f"\n🧠 节点工作负载分布:")
        for (x, y), node in self.nodes.items():
            print(f"   • 节点({x},{y}): {node.workload_config['description']}")
        
        print(f"\n🔗 SST网络组件:")
        print(f"   • 路由器类型: merlin.hr_router")
        print(f"   • 端口配置: 5端口 (东西南北+本地)")
        print(f"   • 拓扑子组件: merlin.mesh")
        print(f"   • 端点组件: 独立merlin.test_nic")
        print(f"   • 连接协议: 符合SST端口协议要求")
        
        print(f"\n🚀 混合SST系统构建完成!")
    
    def get_node(self, x: int, y: int) -> MirandaCPUNode:
        """获取指定坐标的节点"""
        return self.nodes.get((x, y))
    
    def send_message(self, src_x: int, src_y: int, dst_x: int, dst_y: int, message: str, memory_request: bool = False, size_bytes: int = 64):
        """在两个节点间发送消息"""
        if (src_x, src_y) not in self.nodes or (dst_x, dst_y) not in self.nodes:
            print("错误: 源或目标节点不存在")
            return
            
        source_node = self.nodes[(src_x, src_y)]
        self.packet_counter += 1
        source_node.send_packet((dst_x, dst_y), message, self.packet_counter, memory_request, size_bytes)
    
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
        """打印详细的网络流量统计信息"""
        print("\n=== 详细网络流量统计信息 ===")
        
        # 系统级统计
        total_packets_sent = 0
        total_packets_received = 0
        total_packets_forwarded = 0
        total_bytes_sent = 0
        total_bytes_received = 0
        total_bytes_forwarded = 0
        total_latencies = []
        total_hop_counts = []
        
        # 方向流量汇总
        direction_summary = {
            Direction.NORTH: {"packets": 0, "bytes": 0},
            Direction.SOUTH: {"packets": 0, "bytes": 0},
            Direction.EAST: {"packets": 0, "bytes": 0},
            Direction.WEST: {"packets": 0, "bytes": 0},
            Direction.LOCAL: {"packets": 0, "bytes": 0}
        }
        
        # 类型流量汇总
        type_summary = {
            "data": {"packets": 0, "bytes": 0},
            "memory_request": {"packets": 0, "bytes": 0}
        }
        
        print("\n📊 节点级流量统计:")
        print("-" * 100)
        print(f"{'节点':^8} {'发送包':^8} {'接收包':^8} {'转发包':^8} {'发送KB':^8} {'接收KB':^8} {'转发KB':^8} {'平均延迟':^10} {'平均跳数':^8}")
        print("-" * 100)
        
        for (x, y), node in sorted(self.nodes.items()):
            node_info = node.get_node_info()
            
            # 累计系统统计
            total_packets_sent += node_info['packets_sent']
            total_packets_received += node_info['packets_received']
            total_packets_forwarded += node_info['packets_forwarded']
            total_bytes_sent += node_info['bytes_sent']
            total_bytes_received += node_info['bytes_received']
            total_bytes_forwarded += node_info['bytes_forwarded']
            
            if node.packet_latencies:
                total_latencies.extend(node.packet_latencies)
            if node.packets_received > 0:
                total_hop_counts.append(node.total_hop_count / node.packets_received)
            
            # 累计方向流量
            for direction, traffic in node_info['traffic_by_direction'].items():
                direction_summary[direction]["packets"] += traffic["packets"]
                direction_summary[direction]["bytes"] += traffic["bytes"]
            
            # 累计类型流量
            for msg_type, traffic in node_info['traffic_by_type'].items():
                type_summary[msg_type]["packets"] += traffic["packets"]
                type_summary[msg_type]["bytes"] += traffic["bytes"]
            
            print(f"({x},{y}):   {node_info['packets_sent']:^8} {node_info['packets_received']:^8} {node_info['packets_forwarded']:^8} "
                  f"{node_info['bytes_sent']/1024:^8.1f} {node_info['bytes_received']/1024:^8.1f} {node_info['bytes_forwarded']/1024:^8.1f} "
                  f"{node_info['avg_latency_ms']:^10.2f} {node_info['avg_hop_count']:^8.2f}")
        
        print("-" * 100)
        
        # 系统级汇总
        print(f"\n🌐 系统级流量汇总:")
        print(f"   总发送包数: {total_packets_sent:,} 包")
        print(f"   总接收包数: {total_packets_received:,} 包")
        print(f"   总转发包数: {total_packets_forwarded:,} 包")
        print(f"   总数据量: 发送 {total_bytes_sent/1024:.1f} KB, 接收 {total_bytes_received/1024:.1f} KB, 转发 {total_bytes_forwarded/1024:.1f} KB")
        
        success_rate = (total_packets_received / total_packets_sent * 100) if total_packets_sent > 0 else 0
        print(f"   包传递成功率: {success_rate:.2f}%")
        
        if total_latencies:
            avg_latency = sum(total_latencies) / len(total_latencies) * 1000
            print(f"   平均端到端延迟: {avg_latency:.2f} ms")
        
        if total_hop_counts:
            avg_hops = sum(total_hop_counts) / len(total_hop_counts)
            print(f"   平均跳数: {avg_hops:.2f}")
        
        # 方向流量分析
        print(f"\n🧭 按方向流量分析:")
        for direction, traffic in direction_summary.items():
            if traffic["packets"] > 0:
                print(f"   {direction.value:>6}: {traffic['packets']:,} 包, {traffic['bytes']/1024:.1f} KB")
        
        # 消息类型分析
        print(f"\n📨 按消息类型流量分析:")
        for msg_type, traffic in type_summary.items():
            if traffic["packets"] > 0:
                print(f"   {msg_type:>12}: {traffic['packets']:,} 包, {traffic['bytes']/1024:.1f} KB")
        
        # 网络利用率分析
        total_bandwidth = self.total_nodes * 4 * 40  # 假设每节点4个方向，每个40 GiB/s
        total_data_gb = (total_bytes_sent + total_bytes_received + total_bytes_forwarded) / (1024**3)
        utilization = (total_data_gb / total_bandwidth) * 100 if total_bandwidth > 0 else 0
        
        print(f"\n📈 网络性能分析:")
        print(f"   理论总带宽: {total_bandwidth:.1f} GiB/s")
        print(f"   实际数据传输: {total_data_gb*1024:.1f} MiB")
        print(f"   网络利用率: {utilization:.4f}%")
    
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
    
    def get_traffic_matrix(self):
        """生成流量矩阵 - 显示节点间的流量分布"""
        print("\n=== 网络流量矩阵分析 ===")
        
        # 创建流量矩阵
        traffic_matrix = {}
        link_utilization = {}
        
        for (x, y), node in self.nodes.items():
            node_traffic = {}
            
            # 统计每个方向的流量
            for direction, traffic in node.traffic_by_direction.items():
                if traffic["packets"] > 0:
                    neighbor_pos = None
                    if direction == Direction.NORTH and y > 0:
                        neighbor_pos = (x, y-1)
                    elif direction == Direction.SOUTH and y < self.mesh_size_y-1:
                        neighbor_pos = (x, y+1)
                    elif direction == Direction.EAST and x < self.mesh_size_x-1:
                        neighbor_pos = (x+1, y)
                    elif direction == Direction.WEST and x > 0:
                        neighbor_pos = (x-1, y)
                    elif direction == Direction.LOCAL:
                        neighbor_pos = (x, y)
                    
                    if neighbor_pos:
                        node_traffic[neighbor_pos] = traffic
                        
                        # 计算链路利用率
                        if direction != Direction.LOCAL:
                            link_key = tuple(sorted([(x, y), neighbor_pos]))
                            if link_key not in link_utilization:
                                link_utilization[link_key] = {"packets": 0, "bytes": 0}
                            link_utilization[link_key]["packets"] += traffic["packets"]
                            link_utilization[link_key]["bytes"] += traffic["bytes"]
            
            traffic_matrix[(x, y)] = node_traffic
        
        # 打印流量矩阵
        print("\n📊 节点间流量矩阵 (包数/字节数):")
        print("   ", end="")
        for x in range(self.mesh_size_x):
            for y in range(self.mesh_size_y):
                print(f"({x},{y})".ljust(12), end="")
        print()
        
        for src_x in range(self.mesh_size_x):
            for src_y in range(self.mesh_size_y):
                print(f"({src_x},{src_y})".ljust(3), end="")
                for dst_x in range(self.mesh_size_x):
                    for dst_y in range(self.mesh_size_y):
                        traffic = traffic_matrix.get((src_x, src_y), {}).get((dst_x, dst_y), {"packets": 0, "bytes": 0})
                        if traffic["packets"] > 0:
                            print(f"{traffic['packets']}/{traffic['bytes']}".ljust(12), end="")
                        else:
                            print("-".ljust(12), end="")
                print()
        
        # 打印链路利用率
        print("\n🔗 链路利用率分析:")
        if link_utilization:
            print(f"{'链路':^20} {'包数':^8} {'字节数':^10} {'利用率%':^8}")
            print("-" * 50)
            for link, traffic in sorted(link_utilization.items()):
                link_str = f"{link[0]} <-> {link[1]}"
                # 假设链路带宽为40GiB/s，计算利用率
                max_bytes = 40 * 1024**3  # 40 GiB
                utilization = (traffic["bytes"] / max_bytes) * 100
                print(f"{link_str:^20} {traffic['packets']:^8} {traffic['bytes']:^10} {utilization:^8.4f}")
        else:
            print("   无链路流量数据")
        
        return traffic_matrix, link_utilization
    
    def analyze_hotspots(self):
        """分析网络热点和拥塞"""
        print("\n=== 网络热点分析 ===")
        
        # 按流量排序节点
        node_traffic = []
        for (x, y), node in self.nodes.items():
            total_traffic = node.bytes_sent + node.bytes_received + node.bytes_forwarded
            node_traffic.append(((x, y), total_traffic, node.packets_forwarded))
        
        # 按总流量排序
        node_traffic.sort(key=lambda x: x[1], reverse=True)
        
        print("\n🔥 流量热点节点 (按总字节数排序):")
        print(f"{'节点':^8} {'总流量(KB)':^12} {'转发包数':^10} {'工作负载':^20}")
        print("-" * 55)
        
        for i, ((x, y), traffic_bytes, forwarded_packets) in enumerate(node_traffic[:8]):
            node = self.nodes[(x, y)]
            workload = node.workload_config["description"][:18]
            print(f"({x},{y}):   {traffic_bytes/1024:^12.1f} {forwarded_packets:^10} {workload:^20}")
            if i == 0:
                print("   ↑ 最繁忙节点")
        
        # 分析拥塞节点
        congested_nodes = []
        for (x, y), node in self.nodes.items():
            if node.packets_forwarded > 0:
                forwarding_ratio = node.packets_forwarded / (node.packets_sent + node.packets_received + 1)
                if forwarding_ratio > 0.5:  # 转发比例超过50%
                    congested_nodes.append(((x, y), forwarding_ratio))
        
        if congested_nodes:
            congested_nodes.sort(key=lambda x: x[1], reverse=True)
            print(f"\n⚠️  潜在拥塞节点 (转发比例 > 50%):")
            for (x, y), ratio in congested_nodes:
                print(f"   节点({x},{y}): 转发比例 {ratio*100:.1f}%")
        else:
            print(f"\n✅ 无明显拥塞节点")
    
    def generate_traffic_report(self):
        """生成完整的流量分析报告"""
        print("\n" + "="*80)
        print("📈 网络流量完整分析报告")
        print("="*80)
        
        # 基础统计
        self.print_statistics()
        
        # 流量矩阵
        self.get_traffic_matrix()
        
        # 热点分析
        self.analyze_hotspots()
        
        print("\n" + "="*80)
    
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
    """测试混合mesh网络通信 - 使用SST merlin.hr_router，包含详细流量分析"""
    print("=== 混合Miranda Mesh网络通信测试 (SST版本) ===\n")
    
    # 创建混合mesh网络
    mesh = HybridMirandaMesh(
        mesh_size_x=4,
        mesh_size_y=4,
        enable_sst_stats=True,
        verbose=True
    )
    
    # 打印拓扑
    mesh.print_topology()
    
    print("\n=== 开始混合SST系统通信测试 ===")
    
    # 测试场景1: 普通数据通信 (不同大小的数据包)
    print("\n1. 测试普通数据通信:")
    mesh.send_message(0, 0, 0, 1, "Hello from master core", size_bytes=32)
    mesh.send_message(1, 1, 2, 1, "Compute core communication", size_bytes=128)
    
    # 测试场景2: 内存请求通信 (大数据包)
    print("\n2. 测试内存请求通信:")
    mesh.send_message(0, 0, 3, 3, "Memory request to corner", memory_request=True, size_bytes=256)
    mesh.send_message(1, 1, 3, 3, "Cache miss request", memory_request=True, size_bytes=64)
    
    # 测试场景3: 混合通信
    print("\n3. 测试混合通信:")
    mesh.send_message(0, 0, 2, 2, "Data to compute core", size_bytes=512)
    mesh.send_message(2, 2, 0, 0, "Result back to master", memory_request=True, size_bytes=1024)
    
    # 测试场景4: 广播式通信 (一个节点发送到多个节点)
    print("\n4. 测试广播式通信:")
    for x in range(4):
        for y in range(4):
            if x != 0 or y != 0:  # 不发送给自己
                mesh.send_message(0, 0, x, y, f"Broadcast message to ({x},{y})", size_bytes=64)
    
    # 运行模拟
    mesh.simulate(steps=20)  # 增加模拟步数以处理更多流量
    
    # 生成完整的流量分析报告
    mesh.generate_traffic_report()
    
    # 导出SST统计数据
    print("\n=== 导出混合SST系统统计数据 ===")
    mesh.export_sst_statistics()
    
    return mesh


def test_hybrid_workload_patterns():
    """测试混合工作负载模式 - SST merlin.hr_router版本，包含流量模式分析"""
    print("\n\n=== 混合工作负载模式测试 (SST版本) ===")
    
    mesh = HybridMirandaMesh(enable_sst_stats=True, verbose=False)  # 减少输出以专注于统计
    
    print("\n进行工作负载特定的通信测试...")
    
    # 1. 主控核心分发任务 (多种大小的数据包)
    print("\n1. 主控核心分发任务:")
    mesh.send_message(0, 0, 1, 1, "Task distribution to compute cores", size_bytes=256)
    mesh.send_message(0, 0, 2, 2, "Compute task assignment", size_bytes=512)
    mesh.send_message(0, 0, 1, 2, "Additional task data", size_bytes=128)
    mesh.send_message(0, 0, 2, 1, "Coordination message", size_bytes=64)
    
    # 2. 计算核心请求内存 (大数据传输)
    print("\n2. 计算核心请求内存:")
    mesh.send_message(1, 1, 3, 3, "Memory access request", memory_request=True, size_bytes=1024)
    mesh.send_message(2, 2, 3, 3, "Cache miss to memory controller", memory_request=True, size_bytes=2048)
    mesh.send_message(1, 2, 3, 3, "Bulk data request", memory_request=True, size_bytes=4096)
    
    # 3. I/O核心数据流 (持续数据流)
    print("\n3. I/O核心数据流:")
    for i in range(5):  # 模拟连续的I/O操作
        mesh.send_message(0, 1, 1, 2, f"I/O data stream {i}", size_bytes=256)
        mesh.send_message(3, 1, 2, 1, f"I/O response data {i}", size_bytes=128)
    
    # 4. 结果收集
    print("\n4. 结果收集:")
    mesh.send_message(1, 1, 0, 0, "Compute result to master", size_bytes=512)
    mesh.send_message(2, 2, 0, 0, "Processing complete notification", size_bytes=64)
    mesh.send_message(1, 2, 0, 0, "Final results", size_bytes=1024)
    
    # 5. 网络压力测试 - 全对全通信
    print("\n5. 网络压力测试:")
    for src_x in range(4):
        for src_y in range(4):
            for dst_x in range(4):
                for dst_y in range(4):
                    if (src_x, src_y) != (dst_x, dst_y):  # 不发送给自己
                        mesh.send_message(src_x, src_y, dst_x, dst_y, 
                                        f"Stress test from ({src_x},{src_y})", 
                                        size_bytes=32)
    
    # 运行足够长的模拟
    mesh.simulate(steps=30)
    
    # 生成完整的流量分析报告
    mesh.generate_traffic_report()
    
    # 导出统计数据
    mesh.export_sst_statistics()
    
    return mesh


def test_comprehensive_traffic_analysis():
    """综合流量分析测试 - 展示完整的网络监控能力"""
    print("\n\n=== 综合流量分析测试 ===")
    
    mesh = HybridMirandaMesh(enable_sst_stats=True, verbose=False)  # 减少冗余输出
    
    print("正在进行多样化的流量模式测试...")
    
    # 1. 核心间高频通信模式 (热点生成)
    print("\n生成热点流量模式...")
    for i in range(10):
        mesh.send_message(0, 0, 1, 1, f"High-freq comm {i}", size_bytes=64)
        mesh.send_message(1, 1, 0, 0, f"Response {i}", size_bytes=32)
    
    # 2. 大数据传输模式
    print("生成大数据传输...")
    mesh.send_message(0, 0, 3, 3, "Large data transfer", size_bytes=8192)
    mesh.send_message(3, 3, 0, 0, "Large response", size_bytes=4096)
    
    # 3. 分散的小数据包
    print("生成分散的小数据包...")
    for x in range(4):
        for y in range(4):
            mesh.send_message(x, y, (x+1)%4, (y+1)%4, f"Small packet from ({x},{y})", size_bytes=16)
    
    # 4. 内存控制器热点
    print("生成内存控制器热点...")
    for src_x in range(4):
        for src_y in range(4):
            if (src_x, src_y) != (3, 3):  # 除了内存控制器本身
                mesh.send_message(src_x, src_y, 3, 3, 
                                f"Memory request from ({src_x},{src_y})", 
                                memory_request=True, size_bytes=1024)
    
    # 5. 延时敏感的实时通信
    print("生成实时通信模式...")
    for i in range(5):
        mesh.send_message(0, 1, 2, 3, f"Real-time signal {i}", size_bytes=8)
        mesh.send_message(2, 3, 0, 1, f"RT response {i}", size_bytes=8)
    
    # 运行模拟
    mesh.simulate(steps=50)
    
    # 详细分析网络流量
    print("\n" + "="*60)
    print("              流量统计分析报告")
    print("="*60)
    
    # 总体统计
    total_packets = sum(node.packets_sent for node in mesh.get_all_nodes())
    total_bytes = sum(node.total_bytes_sent for node in mesh.get_all_nodes())
    print(f"\n总体统计:")
    print(f"  总数据包数: {total_packets}")
    print(f"  总传输字节: {total_bytes:,} bytes")
    print(f"  平均数据包大小: {total_bytes/total_packets:.1f} bytes" if total_packets > 0 else "  平均数据包大小: 0 bytes")
    
    # 按节点的详细统计
    print(f"\n节点详细统计:")
    for x in range(4):
        for y in range(4):
            node = mesh.mesh[x][y]
            if node.packets_sent > 0 or node.packets_received > 0:
                efficiency = (node.packets_received / node.packets_sent * 100) if node.packets_sent > 0 else 0
                print(f"  节点({x},{y}): 发送 {node.packets_sent} 包/{node.total_bytes_sent:,} bytes, "
                      f"接收 {node.packets_received} 包/{node.total_bytes_received:,} bytes")
                if hasattr(node, 'total_latency') and node.packets_received > 0:
                    avg_latency = node.total_latency / node.packets_received
                    print(f"             平均延时: {avg_latency:.2f} 步")
    
    # 方向性流量分析
    print(f"\n方向性流量分析:")
    directions = ['north', 'south', 'east', 'west']
    for direction in directions:
        total_dir_packets = sum(getattr(node, f'packets_sent_{direction}', 0) for node in mesh.get_all_nodes())
        total_dir_bytes = sum(getattr(node, f'bytes_sent_{direction}', 0) for node in mesh.get_all_nodes())
        if total_dir_packets > 0:
            print(f"  {direction.upper()}方向: {total_dir_packets} 包, {total_dir_bytes:,} bytes")
    
    # 生成流量矩阵
    traffic_matrix = mesh.get_traffic_matrix()
    print(f"\n流量矩阵 (数据包计数):")
    print("     ", end="")
    for x in range(4):
        for y in range(4):
            print(f"({x},{y})".ljust(6), end="")
    print()
    
    for src_x in range(4):
        for src_y in range(4):
            print(f"({src_x},{src_y})", end="")
            for dst_x in range(4):
                for dst_y in range(4):
                    count = traffic_matrix.get((src_x, src_y, dst_x, dst_y), 0)
                    print(f"{count}".ljust(6), end="")
            print()
    
    # 热点分析
    hotspots = mesh.analyze_hotspots()
    print(f"\n热点分析:")
    print(f"  发送热点: {hotspots['senders'][:3]}")  # 前3个
    print(f"  接收热点: {hotspots['receivers'][:3]}")  # 前3个
    
    # 生成完整报告
    mesh.generate_traffic_report()
    
    # 导出数据
    mesh.export_sst_statistics()
    
    return mesh


if __name__ == "__main__":
    # 只在作为主程序运行时执行测试
    print("=== 作为主程序运行混合系统测试 ===")
    
    # 运行综合流量分析测试
    print("\n开始综合流量统计分析...")
    mesh1 = test_comprehensive_traffic_analysis()
    
    print("\n" + "="*60)
    
    # 运行混合系统通信测试
    test_hybrid_mesh_communication()
    
    # 运行混合工作负载测试
    test_hybrid_workload_patterns()
    
    print("\n=== 混合系统测试完成 ===")
    print("流量统计分析报告已生成完毕！")
else:
    # 作为模块导入时，仅打印导入信息
    print("混合Miranda Mesh系统模块已导入 (SST merlin.hr_router版本)")
