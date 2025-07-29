"""
NoC节点封装类
用于构建可复用的片上网络节点组件
"""

import sst

class NoCNode:
    """
    片上网络节点类
    封装了CPU、缓存、内存控制器的完整节点
    """
    
    def __init__(self, node_id, x, y, mesh_size_x, mesh_size_y, 
                 link_bandwidth="40GiB/s", link_latency="50ps", is_memory_node=False):
        """
        初始化NoC节点
        
        Args:
            node_id: 节点ID
            x, y: 节点在mesh网络中的坐标
            mesh_size_x, mesh_size_y: mesh网络的大小
            link_bandwidth: 链路带宽
            link_latency: 链路延迟
            is_memory_node: 是否为内存节点
        """
        self.node_id = node_id
        self.x = x
        self.y = y
        self.mesh_size_x = mesh_size_x
        self.mesh_size_y = mesh_size_y
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        self.is_memory_node = is_memory_node
        
        # 组件引用
        self.cpu = None
        self.l1_cache = None
        self.mem_ctrl = None
        self.mem_backend = None
        
        # 创建节点组件
        self._create_components()
        self._connect_components()
    
    def _create_components(self):
        """创建节点的所有组件"""        
        if self.is_memory_node:
            self._create_memory_controller()
        else:
            self._create_cpu_and_cache()
    
    def _create_cpu_and_cache(self):
        """创建CPU和L1缓存（仅计算节点）"""
        # 创建Miranda CPU核心
        self.cpu = sst.Component(f"cpu_{self.node_id}", "miranda.BaseCPU")
        self.cpu.addParams({
            "clock": "500MHz",
            "verbose": "0",
            "maxmemreqpending": "4",
            "generator": "miranda.SingleStreamGenerator",
            "generatorParams.count": "100",
            "generatorParams.length": "8",
            "generatorParams.start_address": str(self.node_id * 4096),
            "generatorParams.max_address": str((self.node_id + 1) * 4096 - 1),
        })
        
        # 创建L1缓存
        self.l1_cache = sst.Component(f"l1cache_{self.node_id}", "memHierarchy.Cache")
        self.l1_cache.addParams({
            "cache_frequency": "500MHz",
            "cache_size": "8KiB",
            "associativity": "2",
            "access_latency_cycles": "1",
            "cache_line_size": "64",
            "replacement_policy": "lru",
            "coherence_protocol": "none",
            "cache_type": "noninclusive",
        })
    
    def _create_memory_controller(self):
        """创建内存控制器（仅内存节点）"""
        self.mem_ctrl = sst.Component(f"memory_{self.node_id}", "memHierarchy.MemController")
        self.mem_ctrl.addParams({
            "clock": "1GHz",
            "request_width": "64",
            "addr_range_start": "0",
            "addr_range_end": "134217727",  # 128MB
        })
        
        # 创建内存后端
        self.mem_backend = self.mem_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        self.mem_backend.addParams({
            "access_time": "100ns",
            "mem_size": "128MiB",
        })
    
    def _connect_components(self):
        """连接节点内部组件"""
        if not self.is_memory_node:
            # 计算节点：连接CPU -> L1缓存
            cpu_cache_link = sst.Link(f"cpu_cache_link_{self.node_id}")
            cpu_cache_link.connect(
                (self.cpu, "cache_link", "1ns"), 
                (self.l1_cache, "high_network_0", "1ns")
            )
    
    def get_cpu(self):
        """获取CPU组件引用"""
        return self.cpu
    
    def get_cache(self):
        """获取L1缓存组件引用"""
        return self.l1_cache
    
    def get_memory_controller(self):
        """获取内存控制器组件引用"""
        return self.mem_ctrl
    
    def get_info(self):
        """获取节点信息"""
        if self.is_memory_node:
            return {
                "node_id": self.node_id,
                "position": (self.x, self.y),
                "type": "memory"
            }
        else:
            return {
                "node_id": self.node_id,
                "position": (self.x, self.y),
                "type": "compute"
            }


class NoCMesh:
    """
    NoC Mesh网络类
    管理整个mesh网络的构建和配置
    """
    
    def __init__(self, mesh_size_x=4, mesh_size_y=4, 
                 link_bandwidth="40GiB/s", link_latency="50ps",
                 memory_nodes=None):
        """
        初始化NoC Mesh网络
        
        Args:
            mesh_size_x, mesh_size_y: mesh网络大小
            link_bandwidth: 链路带宽
            link_latency: 链路延迟
            memory_nodes: 内存节点位置列表，默认为角落节点
        """
        self.mesh_size_x = mesh_size_x
        self.mesh_size_y = mesh_size_y
        self.total_nodes = mesh_size_x * mesh_size_y
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        
        # 默认将角落节点设为内存节点
        if memory_nodes is None:
            self.memory_nodes = {
                0,  # 左上角 (0,0)
                mesh_size_x - 1,  # 右上角 (mesh_size_x-1, 0)
                (mesh_size_y - 1) * mesh_size_x,  # 左下角 (0, mesh_size_y-1)
                mesh_size_x * mesh_size_y - 1  # 右下角 (mesh_size_x-1, mesh_size_y-1)
            }
        else:
            self.memory_nodes = set(memory_nodes)
        
        self.nodes = []
        
        # 创建所有节点
        self._create_nodes()
    
    def _create_nodes(self):
        """创建所有NoC节点"""
        for i in range(self.total_nodes):
            x = i % self.mesh_size_x
            y = i // self.mesh_size_x
            
            is_memory = i in self.memory_nodes
            
            node = NoCNode(i, x, y, self.mesh_size_x, self.mesh_size_y,
                          self.link_bandwidth, self.link_latency, is_memory)
            self.nodes.append(node)
    
    def get_node(self, node_id):
        """获取指定节点"""
        if 0 <= node_id < len(self.nodes):
            return self.nodes[node_id]
        return None
    
    def get_all_nodes(self):
        """获取所有节点"""
        return self.nodes
    
    def get_compute_nodes(self):
        """获取所有计算节点"""
        return [node for node in self.nodes if not node.is_memory_node]
    
    def get_memory_nodes(self):
        """获取所有内存节点"""
        return [node for node in self.nodes if node.is_memory_node]
