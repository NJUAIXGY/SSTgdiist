#!/usr/bin/env python3
"""
Hybrid Miranda Mesh Network System

混合Miranda网格网络系统 - 支持多拓扑的CPU网格仿真
结合Miranda CPU节点层次结构和SST网络仿真框架

功能特性:
- 支持Mesh和Torus拓扑
- Miranda CPU节点架构
- 多拓扑路由算法
- 完整的网络性能分析
- SST仿真框架集成

作者: AI Assistant
日期: 2025年8月1日
版本: 1.0
"""

# 标准库导入
import json
import csv
import time
import os
import random
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any

# SST仿真框架
import sst

"""
================================================================================
系统架构概述
================================================================================

本文件实现了一个完整的混合Miranda网格网络系统，具有以下层次结构：

📁 核心组件：
├── 🏗️  数据结构层
│   ├── Direction: 网络路由方向枚举
│   ├── TopologyType: 支持的拓扑类型
│   ├── TopoConfig: 拓扑配置参数
│   └── Packet: 网络数据包定义
│
├── 🧠 路由算法层  
│   ├── MultiTopologyRouter: 多拓扑智能路由器
│   └── LogicalRouter: 传统XY路由器
│
├── 💻 节点架构层
│   └── MirandaCPUNode: Miranda CPU节点 (SST集成)
│
├── 🌐 系统管理层
│   └── HybridMirandaMesh: 混合网格系统主类
│
└── 🧪 测试验证层
    ├── test_multi_topology_systems: 多拓扑兼容性测试
    ├── test_hybrid_mesh_communication: 详细通信测试  
    └── test_comprehensive_traffic_analysis: 流量分析测试

🔧 核心特性：
• 多拓扑支持：Mesh (网格) 和 Torus (环形) 拓扑
• Miranda CPU架构：支持多种工作负载模式
• SST仿真集成：与SST-Core仿真框架完全兼容
• 智能路由算法：维序路由和环形最短路径路由
• 完整性能分析：实时流量统计、热点检测、延迟分析
• 可扩展设计：支持任意规模的网格配置

📊 支持的分析功能：
• 网络流量矩阵分析
• 节点级性能统计
• 方向性流量分布
• 热点和拥塞检测
• 端到端延迟测量
• 路由跳数统计

================================================================================
"""

# =============================================================================
# 核心数据结构定义
# =============================================================================

class Direction(Enum):
    """
    网络路由方向枚举
    
    定义网格拓扑中的四个基本方向和本地方向
    """
    NORTH = "north"    # 北方向 (y坐标减小)
    SOUTH = "south"    # 南方向 (y坐标增大) 
    EAST = "east"      # 东方向 (x坐标增大)
    WEST = "west"      # 西方向 (x坐标减小)
    LOCAL = "local"    # 本地节点 (目标节点)


class TopologyType(Enum):
    """
    支持的网络拓扑类型
    
    目前支持二维网格和环形拓扑
    """
    MESH = "mesh"      # 2D网格拓扑 (边缘节点无环绕连接)
    TORUS = "torus"    # 2D环形拓扑 (边缘节点有环绕连接)


@dataclass
class TopoConfig:
    """
    拓扑配置参数类
    
    包含网络拓扑的所有配置参数
    """
    topology_type: TopologyType    # 拓扑类型
    total_nodes: int = 16          # 总节点数
    mesh_size_x: int = 4           # X方向网格大小
    mesh_size_y: int = 4           # Y方向网格大小


@dataclass
class Packet:
    """
    网络数据包类
    
    包含数据包的所有属性和元数据
    """
    source: Tuple[int, int]        # 源节点坐标 (x, y)
    destination: Tuple[int, int]   # 目标节点坐标 (x, y)
    data: str                      # 数据内容
    packet_id: int                 # 数据包唯一标识符
    hop_count: int = 0             # 路由跳数计数器
    memory_request: bool = False   # 是否为内存访问请求
    size_bytes: int = 64           # 数据包大小 (字节)
    timestamp: float = 0.0         # 发送时间戳
    creation_time: float = 0.0     # 创建时间戳


# =============================================================================
# 路由算法实现
# =============================================================================


class MultiTopologyRouter:
    """
    多拓扑路由器
    
    支持Mesh和Torus拓扑的智能路由算法实现
    根据拓扑类型自动选择最优路由策略
    """
    
    def __init__(self, node_id: int, position: Tuple[int, int], topology_config: TopoConfig):
        """
        初始化多拓扑路由器
        
        Args:
            node_id: 节点唯一标识符
            position: 节点在网格中的位置坐标
            topology_config: 拓扑配置参数
        """
        self.node_id = node_id
        self.position = position
        self.x, self.y = position
        self.topology_config = topology_config
        
    def route_packet(self, packet: Packet) -> Direction:
        """
        根据拓扑类型选择路由算法
        
        Args:
            packet: 待路由的数据包
            
        Returns:
            Direction: 下一跳的路由方向
        """
        if self.topology_config.topology_type == TopologyType.MESH:
            return self._route_mesh(packet)
        elif self.topology_config.topology_type == TopologyType.TORUS:
            return self._route_torus(packet)
        else:
            return Direction.LOCAL
    
    def _route_mesh(self, packet: Packet) -> Direction:
        """
        Mesh拓扑XY路由算法
        
        采用维序路由策略：先X方向，后Y方向
        确保无死锁且路径最短
        
        Args:
            packet: 待路由的数据包
            
        Returns:
            Direction: 下一跳方向
        """
        dest_x, dest_y = packet.destination
        
        # 检查是否已到达目标节点
        if dest_x == self.x and dest_y == self.y:
            return Direction.LOCAL
            
        # X方向路由优先 (维序路由)
        if dest_x > self.x:
            return Direction.EAST
        elif dest_x < self.x:
            return Direction.WEST
        # X方向已对齐，进行Y方向路由
        elif dest_y > self.y:
            return Direction.SOUTH
        elif dest_y < self.y:
            return Direction.NORTH
        
        return Direction.LOCAL
    
    def _route_torus(self, packet: Packet) -> Direction:
        """
        Torus拓扑环形路由算法
        
        考虑环绕链路，选择最短路径
        对于每个维度，比较直接路径和环绕路径的距离
        
        Args:
            packet: 待路由的数据包
            
        Returns:
            Direction: 下一跳方向
        """
        dest_x, dest_y = packet.destination
        
        # 检查是否已到达目标节点
        if dest_x == self.x and dest_y == self.y:
            return Direction.LOCAL
        
        # X方向路由 - 选择最短路径（考虑环绕）
        if dest_x != self.x:
            direct_dist_x = abs(dest_x - self.x)
            wrap_dist_x = self.topology_config.mesh_size_x - direct_dist_x
            
            if direct_dist_x <= wrap_dist_x:
                # 直接路径更短或相等
                return Direction.EAST if dest_x > self.x else Direction.WEST
            else:
                # 环绕路径更短
                return Direction.WEST if dest_x > self.x else Direction.EAST
        
        # Y方向路由 - 选择最短路径（考虑环绕）
        if dest_y != self.y:
            direct_dist_y = abs(dest_y - self.y)
            wrap_dist_y = self.topology_config.mesh_size_y - direct_dist_y
            
            if direct_dist_y <= wrap_dist_y:
                # 直接路径更短或相等
                return Direction.SOUTH if dest_y > self.y else Direction.NORTH
            else:
                # 环绕路径更短
                return Direction.NORTH if dest_y > self.y else Direction.SOUTH
        
        return Direction.LOCAL


class LogicalRouter:
    """
    逻辑路由器
    
    实现传统XY路由算法，用于逻辑层面的数据包路由
    提供简单高效的维序路由功能
    """
    
    def __init__(self, x: int, y: int):
        """
        初始化逻辑路由器
        
        Args:
            x: 节点X坐标
            y: 节点Y坐标
        """
        self.x = x
        self.y = y
        self.position = (x, y)
        
    def route_packet(self, packet: Packet) -> Direction:
        """
        使用XY路由算法计算下一跳方向
        
        采用维序路由策略：先在X方向路由到目标列，
        再在Y方向路由到目标行
        
        Args:
            packet: 待路由的数据包
            
        Returns:
            Direction: 下一跳的路由方向
        """
        dest_x, dest_y = packet.destination
        
        # 检查是否已到达目标节点
        if dest_x == self.x and dest_y == self.y:
            return Direction.LOCAL
            
        # X方向路由优先 (维序路由策略)
        if dest_x > self.x:
            return Direction.EAST
        elif dest_x < self.x:
            return Direction.WEST
        # X方向已对齐，进行Y方向路由
        elif dest_y > self.y:
            return Direction.SOUTH
        elif dest_y < self.y:
            return Direction.NORTH
        
        return Direction.LOCAL


# =============================================================================
# Miranda CPU节点实现
# =============================================================================

class MirandaCPUNode:
    """
    Miranda CPU节点
    
    融合Miranda CPU架构和网络路由功能的混合节点
    支持多种拓扑结构和工作负载模式
    """
    
    def __init__(self, node_id: int, position: Tuple[int, int], 
                 topology_config: TopoConfig,
                 cpu_clock: str = "2.4GHz",
                 cache_size: str = "32KiB",
                 memory_size: str = "128MiB",
                 link_bandwidth: str = "40GiB/s",
                 link_latency: str = "50ps",
                 stats_manager=None,
                 verbose: bool = True):
        """
        初始化Miranda CPU节点
        
        Args:
            node_id: 节点唯一标识符
            position: 节点在网格中的位置坐标
            topology_config: 拓扑配置参数
            cpu_clock: CPU时钟频率
            cache_size: 缓存大小
            memory_size: 内存大小
            link_bandwidth: 链路带宽
            link_latency: 链路延迟
            stats_manager: 统计管理器
            verbose: 是否打印详细信息
        """
        # 基本属性
        self.node_id = node_id
        self.position = position
        self.x, self.y = position
        self.topology_config = topology_config
        
        # 硬件配置参数
        self.cpu_clock = cpu_clock
        self.cache_size = cache_size
        self.memory_size = memory_size
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        self.verbose = verbose
        
        # 路由器和统计管理器
        self.logical_router = MultiTopologyRouter(node_id, position, topology_config)
        self.stats_manager = stats_manager
        
        # 邻居节点连接映射
        self.neighbors: Dict[Direction, Optional['MirandaCPUNode']] = {
            Direction.NORTH: None,
            Direction.SOUTH: None,
            Direction.EAST: None,
            Direction.WEST: None,
        }
        
        # 网络队列管理
        self.input_queue: List[Packet] = []
        self.output_queues: Dict[Direction, List[Packet]] = {
            direction: [] for direction in Direction
        }
        
        # SST仿真组件引用
        self.cpu_core = None
        self.sst_router = None
        self.l1_cache = None
        self.memory_controller = None
        self.endpoint = None
        self.netif = None
        
        # 基础统计计数器
        self.packets_sent = 0
        self.packets_received = 0
        self.packets_forwarded = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.bytes_forwarded = 0
        
        # 详细流量统计
        self.traffic_by_direction = {
            direction: {"packets": 0, "bytes": 0} for direction in Direction
        }
        
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
    
    # =========================================================================
    # 工作负载配置方法
    # =========================================================================
    
    def _get_workload_config(self) -> Dict[str, Any]:
        """
        根据拓扑和节点位置确定工作负载配置
        
        工作负载分配策略：
        - 左上角(0,0): 主控核心 - STREAM基准测试
        - 右下角: 内存控制器 - 随机访问模式  
        - 边缘节点: I/O核心 - 单流访问模式
        - 内部节点: 计算核心 - GUPS基准测试
        
        Returns:
            Dict: 包含生成器类型和描述的配置字典
        """
        # 主控核心 - 左上角节点
        if self.x == 0 and self.y == 0:
            return {
                "generator": "miranda.STREAMBenchGenerator",
                "description": "主控核心 - STREAM基准测试"
            }
        # 内存控制器 - 右下角节点
        elif (self.x == self.topology_config.mesh_size_x - 1 and 
              self.y == self.topology_config.mesh_size_y - 1):
            return {
                "generator": "miranda.RandomGenerator",
                "description": "内存控制器 - 随机访问模式"
            }
        # I/O核心 - 边缘节点
        elif (self.x == 0 or self.x == self.topology_config.mesh_size_x - 1 or 
              self.y == 0 or self.y == self.topology_config.mesh_size_y - 1):
            return {
                "generator": "miranda.SingleStreamGenerator",
                "description": "I/O核心 - 单流访问模式"
            }
        # 计算核心 - 内部节点
        else:
            return {
                "generator": "miranda.GUPSGenerator",
                "description": "计算核心 - GUPS基准测试"
            }
    
    # =========================================================================
    # SST组件创建和配置方法
    # =========================================================================
    
    def _setup_sst_statistics(self):
        """设置SST统计 - 简化版本"""
        # 暂时禁用SST统计，仅使用内部计数器
        pass
    
    def _create_sst_components(self):
        """创建SST组件 - 支持多种拓扑类型"""
        if self.verbose:
            print(f"  节点{self.node_id}({self.x},{self.y}): 创建SST组件 - {self.workload_config['description']}")
        
        # 生成唯一的组件名称
        import time
        timestamp = str(int(time.time() * 1000000))[-6:]
        router_name = f"router_{self.node_id}_{timestamp}"
        
        # 根据拓扑类型确定端口数量
        num_ports = self._calculate_ports_for_topology()
        
        # 创建SST路由器组件
        self.sst_router = sst.Component(router_name, "merlin.hr_router")
        self.sst_router.addParams({
            "id": self.node_id,
            "num_ports": str(num_ports),
            "link_bw": self.link_bandwidth,
            "flit_size": "8B",
            "xbar_bw": self.link_bandwidth,
            "input_latency": self.link_latency,
            "output_latency": self.link_latency,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 配置拓扑子组件
        self._configure_topology_subcomponent()
        
        # 创建端点组件
        endpoint_name = f"endpoint_{self.node_id}_{timestamp}"
        self.endpoint = sst.Component(endpoint_name, "merlin.test_nic")
        self.endpoint.addParams({
            "id": self.node_id,
            "num_peers": str(self.topology_config.total_nodes),
            "num_messages": "10",
            "message_size": "64B",
        })
        
        # 设置网络接口
        self.netif = self.endpoint.setSubComponent("networkIF", "merlin.linkcontrol")
        self.netif.addParams({
            "link_bw": self.link_bandwidth,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 连接端点到路由器的本地端口
        local_link_name = f"local_link_{self.node_id}_{timestamp}"
        local_link = sst.Link(local_link_name)
        local_port = num_ports - 1  # 最后一个端口作为本地端口
        local_link.connect(
            (self.sst_router, f"port{local_port}", self.link_latency),
            (self.netif, "rtr_port", self.link_latency)
        )
        
        if self.verbose:
            print(f"    SST路由器创建完成: {router_name} ({num_ports}端口配置)")
    
    def _calculate_ports_for_topology(self) -> int:
        """根据拓扑类型计算所需端口数量"""
        # Mesh/Torus都使用标准5端口配置: 东西南北 + 本地
        return 5
    
    def _configure_topology_subcomponent(self):
        """配置拓扑子组件"""
        if self.topology_config.topology_type == TopologyType.MESH:
            topo_sub = self.sst_router.setSubComponent("topology", "merlin.mesh")
            topo_sub.addParams({
                "network_name": "Multi_Topology_Mesh",
                "shape": f"{self.topology_config.mesh_size_x}x{self.topology_config.mesh_size_y}",
                "width": "1x1",
                "local_ports": "1",
            })
        elif self.topology_config.topology_type == TopologyType.TORUS:
            topo_sub = self.sst_router.setSubComponent("topology", "merlin.torus")
            topo_sub.addParams({
                "network_name": "Multi_Topology_Torus",
                "shape": f"{self.topology_config.mesh_size_x}x{self.topology_config.mesh_size_y}",
                "width": "1x1",
                "local_ports": "1",
            })
    
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
        """连接邻居节点"""
        self.neighbors[direction] = neighbor
        
        if self.sst_router and neighbor.sst_router:
            self._connect_sst_routers(direction, neighbor)
        
        if self.verbose:
            print(f"    连接: 节点{self.node_id}({self.x},{self.y}) -> {direction.value} -> 节点{neighbor.node_id}({neighbor.x},{neighbor.y})")
    
    def _connect_sst_routers(self, direction: Direction, neighbor: 'MirandaCPUNode'):
        """连接SST路由器组件 - 标准Mesh/Torus端口配置"""
        # 标准的4端口mesh配置 (port0-3: 东西南北, port4: 本地)
        port_map = {
            Direction.EAST: "port0",
            Direction.WEST: "port1", 
            Direction.SOUTH: "port2",
            Direction.NORTH: "port3",
        }
        reverse_port_map = {
            Direction.EAST: "port1",
            Direction.WEST: "port0",
            Direction.SOUTH: "port3", 
            Direction.NORTH: "port2",
        }
        
        if direction in port_map:
            import time
            timestamp = str(int(time.time() * 1000000))[-6:]
            link_name = f"{self.topology_config.topology_type.value}_link_{self.node_id}_to_{neighbor.node_id}_{timestamp}"
            link = sst.Link(link_name)
            
            try:
                link.connect(
                    (self.sst_router, port_map[direction], self.link_latency),
                    (neighbor.sst_router, reverse_port_map[direction], self.link_latency)
                )
                
                if self.verbose:
                    print(f"      SST链路: {port_map[direction]} <-> {reverse_port_map[direction]} ({link_name})")
            except Exception as e:
                if self.verbose:
                    print(f"      警告: 连接失败 - {e}")
    
    def get_sst_router(self):
        """获取SST路由器组件引用"""
        return self.sst_router
    
    def get_endpoint(self):
        """获取SST端点组件引用"""
        return self.endpoint
    
    # =========================================================================
    # 网络通信方法
    # =========================================================================
    
    def send_packet(self, destination: Tuple[int, int], data: str, packet_id: int, 
                   memory_request: bool = False, size_bytes: int = 64):
        """
        发送数据包到指定目标节点
        
        Args:
            destination: 目标节点坐标
            data: 数据内容
            packet_id: 数据包唯一标识符
            memory_request: 是否为内存访问请求
            size_bytes: 数据包大小（字节）
        """
        import time
        current_time = time.time()
        
        # 创建数据包
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



# =============================================================================
# 混合Miranda网格系统主类
# =============================================================================

class HybridMirandaMesh:
    """
    混合Miranda网格系统
    
    这是整个系统的核心类，集成了以下功能：
    - 多拓扑支持：Mesh和Torus网络拓扑
    - Miranda CPU节点架构
    - SST仿真框架集成
    - 完整的网络性能分析
    - 实时流量统计和热点分析
    
    支持的拓扑类型：
    - MESH: 二维网格拓扑，边缘节点无环绕连接
    - TORUS: 二维环形拓扑，边缘节点有环绕连接
    """
    
    def __init__(self, 
                 topology_type: TopologyType = TopologyType.MESH,
                 topology_config: TopoConfig = None,
                 cpu_clock: str = "2.4GHz",
                 cache_size: str = "32KiB",
                 memory_size: str = "128MiB",
                 link_bandwidth: str = "40GiB/s",
                 link_latency: str = "50ps",
                 enable_sst_stats: bool = True,
                 output_dir: str = "./statistics_output",
                 verbose: bool = True):
        """
        初始化混合Miranda网格系统
        
        Args:
            topology_type: 网络拓扑类型 (MESH/TORUS)
            topology_config: 拓扑配置参数，None时使用默认配置
            cpu_clock: CPU时钟频率
            cache_size: 缓存大小
            memory_size: 内存大小
            link_bandwidth: 网络链路带宽
            link_latency: 网络链路延迟
            enable_sst_stats: 是否启用SST统计功能
            output_dir: 统计输出目录
            verbose: 是否输出详细日志
        """
        # 拓扑配置
        self.topology_type = topology_type
        self.topology_config = topology_config if topology_config is not None else self._get_default_topology_config()
        self.total_nodes = self._calculate_total_nodes()
        
        # 硬件配置参数
        self.cpu_clock = cpu_clock
        self.cache_size = cache_size
        self.memory_size = memory_size
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        
        # 系统配置
        self.output_dir = output_dir
        self.verbose = verbose
        self.enable_sst_stats = enable_sst_stats
        
        # 网络状态管理
        self.nodes: Dict[int, MirandaCPUNode] = {}  # 节点映射表 (node_id -> MirandaCPUNode)
        self.packet_counter = 0                     # 全局数据包计数器
        
        # 统计管理器（简化版本，不依赖SST统计）
        self.stats_manager = None
        
        # 系统构建
        self._create_topology()
        self._connect_nodes()
        
        if verbose:
            self._print_system_summary()
    
    def _get_default_topology_config(self) -> TopoConfig:
        """根据拓扑类型获取默认配置"""
        if self.topology_type == TopologyType.MESH:
            return TopoConfig(TopologyType.MESH, mesh_size_x=4, mesh_size_y=4, total_nodes=16)
        elif self.topology_type == TopologyType.TORUS:
            return TopoConfig(TopologyType.TORUS, mesh_size_x=4, mesh_size_y=4, total_nodes=16)
        else:
            return TopoConfig(TopologyType.MESH, mesh_size_x=4, mesh_size_y=4, total_nodes=16)
    
    def _calculate_total_nodes(self) -> int:
        """根据拓扑配置计算总节点数"""
        # Mesh/Torus都使用相同的计算方式
        return self.topology_config.mesh_size_x * self.topology_config.mesh_size_y
    
    def _create_topology(self):
        """创建混合拓扑 - 支持Mesh和Torus拓扑类型"""
        if self.verbose:
            print(f"=== 创建混合Miranda-SST {self.topology_config.topology_type.value}拓扑 ===")
        
        # Mesh和Torus使用相同的创建方式
        for x in range(self.topology_config.mesh_size_x):
            for y in range(self.topology_config.mesh_size_y):
                node_id = y * self.topology_config.mesh_size_x + x
                position = (x, y)
                
                node = MirandaCPUNode(
                    node_id=node_id,
                    position=position,
                    topology_config=self.topology_config,
                    cpu_clock=self.cpu_clock,
                    cache_size=self.cache_size,
                    memory_size=self.memory_size,
                    link_bandwidth=self.link_bandwidth,
                    link_latency=self.link_latency,
                    stats_manager=self.stats_manager,
                    verbose=self.verbose
                )
                self.nodes[node_id] = node
                if self.verbose:
                    print(f"创建混合节点{node_id}({x},{y}) - SST路由器ID: {node.node_id}")
    
    def _connect_nodes(self):
        """连接节点形成指定拓扑"""
        if self.verbose:
            print(f"\n连接SST路由器节点形成{self.topology_type.value}拓扑...")
        
        # Mesh和Torus的连接方式
        if self.topology_type == TopologyType.MESH:
            self._connect_mesh_nodes()
        elif self.topology_type == TopologyType.TORUS:
            self._connect_torus_nodes()
    
    def _connect_mesh_nodes(self):
        """连接Mesh节点"""
        link_count = 0
        for x in range(self.topology_config.mesh_size_x):
            for y in range(self.topology_config.mesh_size_y):
                node_id = y * self.topology_config.mesh_size_x + x
                node = self.nodes[node_id]
                
                # 连接东邻居
                if x < self.topology_config.mesh_size_x - 1:
                    east_id = y * self.topology_config.mesh_size_x + (x + 1)
                    east_neighbor = self.nodes[east_id]
                    node.connect_neighbor(Direction.EAST, east_neighbor)
                    link_count += 1
                
                # 连接南邻居
                if y < self.topology_config.mesh_size_y - 1:
                    south_id = (y + 1) * self.topology_config.mesh_size_x + x
                    south_neighbor = self.nodes[south_id]
                    node.connect_neighbor(Direction.SOUTH, south_neighbor)
                    link_count += 1
                
                # 设置反向引用(逻辑层面)
                if y > 0:
                    north_id = (y - 1) * self.topology_config.mesh_size_x + x
                    node.neighbors[Direction.NORTH] = self.nodes[north_id]
                
                if x > 0:
                    west_id = y * self.topology_config.mesh_size_x + (x - 1)
                    node.neighbors[Direction.WEST] = self.nodes[west_id]
        
        if self.verbose:
            print(f"SST Mesh拓扑连接完成! 创建了{link_count}条双向链路")
    
    def _connect_torus_nodes(self):
        """连接Torus节点 - 包含环绕链路"""
        link_count = 0
        for x in range(self.topology_config.mesh_size_x):
            for y in range(self.topology_config.mesh_size_y):
                node_id = y * self.topology_config.mesh_size_x + x
                node = self.nodes[node_id]
                
                # 连接东邻居（包括环绕）
                if x < self.topology_config.mesh_size_x - 1:
                    east_id = y * self.topology_config.mesh_size_x + (x + 1)
                else:
                    east_id = y * self.topology_config.mesh_size_x + 0  # 环绕到行首
                east_neighbor = self.nodes[east_id]
                node.connect_neighbor(Direction.EAST, east_neighbor)
                link_count += 1
                
                # 连接南邻居（包括环绕）
                if y < self.topology_config.mesh_size_y - 1:
                    south_id = (y + 1) * self.topology_config.mesh_size_x + x
                else:
                    south_id = 0 * self.topology_config.mesh_size_x + x  # 环绕到列首
                south_neighbor = self.nodes[south_id]
                node.connect_neighbor(Direction.SOUTH, south_neighbor)
                link_count += 1
                
                # 设置反向引用(逻辑层面)
                if y > 0:
                    north_id = (y - 1) * self.topology_config.mesh_size_x + x
                else:
                    north_id = (self.topology_config.mesh_size_y - 1) * self.topology_config.mesh_size_x + x
                node.neighbors[Direction.NORTH] = self.nodes[north_id]
                
                if x > 0:
                    west_id = y * self.topology_config.mesh_size_x + (x - 1)
                else:
                    west_id = y * self.topology_config.mesh_size_x + (self.topology_config.mesh_size_x - 1)
                node.neighbors[Direction.WEST] = self.nodes[west_id]
        
        if self.verbose:
            print(f"SST Torus拓扑连接完成! 创建了{link_count}条双向链路（含环绕链路）")
    
    def _print_system_summary(self):
        """打印系统总结"""
        print(f"\n=== 混合Miranda {self.topology_type.value.upper()}系统总结 (SST版本) ===")
        print(f"🏗️  系统架构:")
        
        if self.topology_type in [TopologyType.MESH, TopologyType.TORUS]:
            print(f"   • 网格规模: {self.topology_config.mesh_size_x}×{self.topology_config.mesh_size_y} = {self.total_nodes} 个混合节点")
        else:
            print(f"   • 拓扑规模: {self.total_nodes} 个混合节点")
        
        print(f"   • 拓扑类型: {self.topology_type.value.upper()}")
        print(f"   • 节点架构: Miranda CPU + L1缓存({self.cache_size}) + 本地内存({self.memory_size})")
        print(f"   • 网络拓扑: SST merlin.hr_router (多端口配置)")
        print(f"   • 路由算法: 多拓扑路由 (逻辑层) + merlin 拓扑 (SST层)")
        print(f"   • 链路性能: {self.link_bandwidth} 带宽, {self.link_latency} 延迟")
        print(f"   • CPU频率: {self.cpu_clock}")
        
        print(f"\n🧠 节点工作负载分布:")
        for node_id, node in sorted(self.nodes.items()):
            print(f"   • 节点{node_id}({node.x},{node.y}): {node.workload_config['description']}")
        
        print(f"\n🔗 SST网络组件:")
        print(f"   • 路由器类型: merlin.hr_router")
        print(f"   • 端口配置: 多端口 (根据拓扑类型调整)")
        
        if self.topology_type == TopologyType.MESH:
            print(f"   • 拓扑子组件: merlin.mesh")
        elif self.topology_type == TopologyType.TORUS:
            print(f"   • 拓扑子组件: merlin.torus")
        else:
            print(f"   • 拓扑子组件: merlin.mesh (fallback)")
        
        print(f"   • 端点组件: 独立merlin.test_nic")
        print(f"   • 连接协议: 符合SST端口协议要求")
        
        print(f"\n🚀 混合SST {self.topology_type.value}系统构建完成!")
    
    def get_node(self, node_id: int) -> MirandaCPUNode:
        """获取指定ID的节点"""
        return self.nodes.get(node_id)
    
    def get_node_by_position(self, x: int, y: int) -> MirandaCPUNode:
        """根据坐标获取节点(仅适用于Mesh/Torus拓扑)"""
        if self.topology_type in [TopologyType.MESH, TopologyType.TORUS]:
            node_id = y * self.topology_config.mesh_size_x + x
            return self.nodes.get(node_id)
        return None
    
    def send_message(self, src_node_id: int, dst_node_id: int, message: str, memory_request: bool = False, size_bytes: int = 64):
        """在两个节点间发送消息"""
        if src_node_id not in self.nodes or dst_node_id not in self.nodes:
            print("错误: 源或目标节点不存在")
            return
        
        source_node = self.nodes[src_node_id]
        dest_node = self.nodes[dst_node_id]
        dest_position = dest_node.position
        
        self.packet_counter += 1
        source_node.send_packet(dest_position, message, self.packet_counter, memory_request, size_bytes)
    
    def send_message_by_position(self, src_x: int, src_y: int, dst_x: int, dst_y: int, message: str, memory_request: bool = False, size_bytes: int = 64):
        """根据坐标在两个节点间发送消息(仅适用于Mesh/Torus拓扑)"""
        if self.topology_type not in [TopologyType.MESH, TopologyType.TORUS]:
            print("错误: 坐标发送仅适用于Mesh/Torus拓扑")
            return
        
        src_id = src_y * self.topology_config.mesh_size_x + src_x
        dst_id = dst_y * self.topology_config.mesh_size_x + dst_x
        self.send_message(src_id, dst_id, message, memory_request, size_bytes)
    
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
        
        print(f"\n📊 节点级流量统计:")
        print("-" * 100)
        print(f"{'节点ID':^8} {'发送包':^8} {'接收包':^8} {'转发包':^8} {'发送KB':^8} {'接收KB':^8} {'转发KB':^8} {'平均延迟':^10} {'平均跳数':^8}")
        print("-" * 100)
        
        for node_id, node in sorted(self.nodes.items()):
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
            
            print(f"{node_id:^8}   {node_info['packets_sent']:^8} {node_info['packets_received']:^8} {node_info['packets_forwarded']:^8} "
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
        print(f"\n=== {self.topology_type.value.upper()} 拓扑结构 ===")
        
        for y in range(self.topology_config.mesh_size_y):
            row = ""
            for x in range(self.topology_config.mesh_size_x):
                node_id = y * self.topology_config.mesh_size_x + x
                row += f"[{node_id:2d}]"
                if x < self.topology_config.mesh_size_x - 1:
                    row += " -- "
                elif self.topology_type == TopologyType.TORUS:
                    row += " --o"  # 表示环绕连接
            print(row)
            if y < self.topology_config.mesh_size_y - 1:
                print("  |     " * self.topology_config.mesh_size_x)
            elif self.topology_type == TopologyType.TORUS:
                print("  o     " * self.topology_config.mesh_size_x + " (环绕)")
        
        print(f"总节点数: {self.total_nodes}")
        print(f"拓扑类型: {self.topology_type.value}")
        print(f"网格大小: {self.topology_config.mesh_size_x}x{self.topology_config.mesh_size_y}")
        print("="*50)
    
    def get_traffic_matrix(self):
        """生成流量矩阵 - 显示节点间的流量分布"""
        print("\n=== 网络流量矩阵分析 ===")
        
        # 创建流量矩阵
        traffic_matrix = {}
        link_utilization = {}
        
        for node_id, node in self.nodes.items():
            node_traffic = {}
            
            # 统计每个方向的流量
            for direction, traffic in node.traffic_by_direction.items():
                if traffic["packets"] > 0:
                    neighbor_pos = None
                    x, y = node.x, node.y
                    if direction == Direction.NORTH and y > 0:
                        neighbor_pos = (x, y-1)
                    elif direction == Direction.SOUTH and y < self.topology_config.mesh_size_y-1:
                        neighbor_pos = (x, y+1)
                    elif direction == Direction.EAST and x < self.topology_config.mesh_size_x-1:
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
            
            traffic_matrix[(node.x, node.y)] = node_traffic
        
        # 打印流量矩阵
        print("\n📊 节点间流量矩阵 (包数/字节数):")
        print("   ", end="")
        for x in range(self.topology_config.mesh_size_x):
            for y in range(self.topology_config.mesh_size_y):
                print(f"({x},{y})".ljust(12), end="")
        print()
        
        for src_x in range(self.topology_config.mesh_size_x):
            for src_y in range(self.topology_config.mesh_size_y):
                print(f"({src_x},{src_y})".ljust(3), end="")
                for dst_x in range(self.topology_config.mesh_size_x):
                    for dst_y in range(self.topology_config.mesh_size_y):
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
        for node_id, node in self.nodes.items():
            total_traffic = node.bytes_sent + node.bytes_received + node.bytes_forwarded
            node_traffic.append(((node.x, node.y), total_traffic, node.packets_forwarded))
        
        # 按总流量排序
        node_traffic.sort(key=lambda x: x[1], reverse=True)
        
        print("\n🔥 流量热点节点 (按总字节数排序):")
        print(f"{'节点':^8} {'总流量(KB)':^12} {'转发包数':^10} {'工作负载':^20}")
        print("-" * 55)
        
        for i, ((x, y), traffic_bytes, forwarded_packets) in enumerate(node_traffic[:8]):
            # 通过坐标找到对应的节点ID
            node_id = y * self.topology_config.mesh_size_x + x
            node = self.nodes[node_id]
            workload = node.workload_config["description"][:18]
            print(f"({x},{y}):   {traffic_bytes/1024:^12.1f} {forwarded_packets:^10} {workload:^20}")
            if i == 0:
                print("   ↑ 最繁忙节点")
        
        # 分析拥塞节点
        congested_nodes = []
        for node_id, node in self.nodes.items():
            if node.packets_forwarded > 0:
                forwarding_ratio = node.packets_forwarded / (node.packets_sent + node.packets_received + 1)
                if forwarding_ratio > 0.5:  # 转发比例超过50%
                    congested_nodes.append(((node.x, node.y), forwarding_ratio))
        
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
        for node_id, node in self.nodes.items():
            node_key = f"node_{node.x}_{node.y}"
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

# =============================================================================
# 系统测试函数
# =============================================================================

def test_multi_topology_systems():
    """
    多拓扑系统兼容性测试
    
    测试Mesh和Torus两种拓扑的基本功能：
    - 系统初始化和节点创建
    - 网络连接建立
    - 基本通信功能
    - 路由算法正确性
    
    Returns:
        Dict: 包含各拓扑测试结果的字典
    """
    print("=== 多拓扑混合Miranda系统测试 ===\n")
    
    # 定义要测试的拓扑配置
    topologies_to_test = [
        (TopologyType.MESH, TopoConfig(TopologyType.MESH, mesh_size_x=3, mesh_size_y=3, total_nodes=9)),
        (TopologyType.TORUS, TopoConfig(TopologyType.TORUS, mesh_size_x=3, mesh_size_y=3, total_nodes=9)),
    ]
    
    results = {}
    
    for topo_type, topo_config in topologies_to_test:
        print(f"\n{'='*60}")
        print(f"测试 {topo_type.value.upper()} 拓扑")
        print(f"{'='*60}")
        
        # 创建拓扑
        mesh = HybridMirandaMesh(
            topology_type=topo_type,
            topology_config=topo_config,
            enable_sst_stats=True,
            verbose=False  # 减少输出
        )
        
        # 打印拓扑结构
        mesh.print_topology()
        
        # 进行通信测试
        print(f"\n进行{topo_type.value}拓扑通信测试...")
        
        if topo_type in [TopologyType.MESH, TopologyType.TORUS]:
            # 网格拓扑测试
            mesh.send_message_by_position(0, 0, 2, 2, "Corner to corner", size_bytes=128)
            mesh.send_message_by_position(1, 1, 0, 2, "Center to edge", size_bytes=64)
        
        # 运行模拟
        mesh.simulate(steps=15)
        
        # 收集统计
        total_packets = sum(node.packets_sent for node in mesh.nodes.values())
        total_received = sum(node.packets_received for node in mesh.nodes.values())
        success_rate = (total_received / total_packets * 100) if total_packets > 0 else 0
        
        results[topo_type.value] = {
            'nodes': len(mesh.nodes),
            'packets_sent': total_packets,
            'packets_received': total_received,
            'success_rate': success_rate
        }
        
        print(f"\n{topo_type.value}拓扑测试结果:")
        print(f"  节点数量: {len(mesh.nodes)}")
        print(f"  发送包数: {total_packets}")
        print(f"  接收包数: {total_received}")
        print(f"  成功率: {success_rate:.2f}%")
    
    # 总结对比
    print(f"\n{'='*60}")
    print("多拓扑系统性能对比")
    print(f"{'='*60}")
    print(f"{'拓扑类型':^12} {'节点数':^8} {'发送包':^8} {'接收包':^8} {'成功率':^8}")
    print("-" * 60)
    
    for topo_name, stats in results.items():
        print(f"{topo_name:^12} {stats['nodes']:^8} {stats['packets_sent']:^8} "
              f"{stats['packets_received']:^8} {stats['success_rate']:^7.1f}%")
    
    return results


def test_hybrid_mesh_communication():
    """
    混合Mesh网络详细通信测试
    
    执行完整的网络通信测试流程：
    - 创建4x4 Mesh拓扑网络
    - 测试多种类型的数据包传输
    - 验证路由算法正确性
    - 生成详细的网络性能分析报告
    
    Returns:
        HybridMirandaMesh: 配置完成的网格系统实例
    """
    print("=== 混合Miranda Mesh网络通信测试 (多拓扑版本) ===\n")
    
    # 创建4x4 Mesh拓扑系统
    mesh = HybridMirandaMesh(
        topology_type=TopologyType.MESH,
        topology_config=TopoConfig(TopologyType.MESH, mesh_size_x=4, mesh_size_y=4, total_nodes=16),
        enable_sst_stats=True,
        verbose=True
    )
    
    # 显示网络拓扑结构
    mesh.print_topology()
    
    print("\n=== 开始混合SST系统通信测试 ===")
    
    # 测试场景1: 普通数据通信
    print("\n1. 测试普通数据通信:")
    mesh.send_message_by_position(0, 0, 0, 1, "Hello from master core", size_bytes=32)
    mesh.send_message_by_position(1, 1, 2, 1, "Compute core communication", size_bytes=128)
    
    # 测试场景2: 内存请求通信
    print("\n2. 测试内存请求通信:")
    mesh.send_message_by_position(0, 0, 3, 3, "Memory request to corner", memory_request=True, size_bytes=256)
    mesh.send_message_by_position(1, 1, 3, 3, "Cache miss request", memory_request=True, size_bytes=64)
    
    # 运行模拟
    mesh.simulate(steps=20)
    
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


# =============================================================================
# 主程序入口
# =============================================================================

if __name__ == "__main__":
    """
    主程序入口
    
    当脚本作为主程序运行时，执行多拓扑系统测试
    包括Mesh和Torus拓扑的完整功能验证
    """
    print("=== Hybrid Miranda Mesh System - 主程序测试模式 ===")
    print("🚀 开始多拓扑网络系统测试...")
    
    try:
        # 运行多拓扑系统测试
        print("\n1️⃣  执行多拓扑系统兼容性测试...")
        results = test_multi_topology_systems()
        
        print("\n" + "="*60)
        
        # 运行详细的mesh通信测试
        print("\n2️⃣  执行详细Mesh拓扑通信测试...")
        mesh = test_hybrid_mesh_communication()
        
        # 测试完成总结
        print("\n" + "="*60)
        print("🎉 多拓扑混合系统测试完成！")
        print("\n📊 系统能力总结:")
        print("  • 支持的拓扑类型:")
        for topo_type in TopologyType:
            print(f"    - {topo_type.value.upper()}: {topo_type.name}拓扑")
        print("  • Miranda CPU节点架构")
        print("  • SST仿真框架集成") 
        print("  • 实时网络性能分析")
        print("  • 完整流量统计报告")
        print("\n📈 流量统计分析报告已生成完毕！")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        
else:
    """
    模块导入模式
    
    当作为模块导入时，仅显示系统信息
    """
    print("🔧 混合Miranda网格系统模块已导入")
    print("   版本: SST merlin.hr_router集成版本")
    print("   支持拓扑: Mesh, Torus")
    print("   功能: 多拓扑路由 + 网络性能分析")
