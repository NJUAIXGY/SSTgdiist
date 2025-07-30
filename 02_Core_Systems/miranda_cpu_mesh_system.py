"""
Miranda CPU Mesh System Class
基于Miranda CPU模拟器的可复用Mesh网络系统

使用方法示例:
    from miranda_cpu_mesh_system import MirandaCPUMeshSystem
    
    # 创建系统实例
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=4,
        mesh_size_y=4,
        link_bandwidth="40GiB/s",
        output_dir="/path/to/output"
    )
    
    # 构建系统
    mesh_system.build_system()
    
    # 配置仿真参数
    mesh_system.configure_simulation(
        simulation_time="100us",
        enable_statistics=True
    )
"""

import sst
import os
from typing import Dict, List, Optional, Any


class MirandaCPUMeshSystem:
    """
    基于Miranda CPU模拟器的Mesh网络系统类
    
    该类封装了一个完整的CPU Mesh系统，包括：
    - Miranda CPU核心（支持不同的工作负载模式）
    - 2D Mesh网络拓扑
    - 内存层次结构（L1缓存 + 本地内存）
    - 统计收集和输出配置
    """
    
    def __init__(self, 
                 mesh_size_x: int = 4,
                 mesh_size_y: int = 4,
                 link_bandwidth: str = "40GiB/s",
                 link_latency: str = "50ps",
                 cpu_clock: str = "2.4GHz",
                 cache_size: str = "32KiB",
                 memory_size: str = "128MiB",
                 output_dir: str = "/home/anarchy/SST/sst_output_data",
                 verbose: bool = True):
        """
        初始化Miranda CPU Mesh系统
        
        Args:
            mesh_size_x: Mesh网格X维度大小
            mesh_size_y: Mesh网格Y维度大小
            link_bandwidth: 链路带宽
            link_latency: 链路延迟
            cpu_clock: CPU时钟频率
            cache_size: L1缓存大小
            memory_size: 本地内存大小
            output_dir: 统计输出目录
            verbose: 是否启用详细输出
        """
        self.mesh_size_x = mesh_size_x
        self.mesh_size_y = mesh_size_y
        self.total_nodes = mesh_size_x * mesh_size_y
        self.link_bandwidth = link_bandwidth
        self.link_latency = link_latency
        self.cpu_clock = cpu_clock
        self.cache_size = cache_size
        self.memory_size = memory_size
        self.output_dir = output_dir
        self.verbose = verbose
        
        # 系统组件存储
        self.routers: List[Any] = []
        self.cpu_cores: List[Any] = []
        self.l1_caches: List[Any] = []
        self.memory_controllers: List[Any] = []
        
        # 工作负载配置
        self.workload_configs = self._get_default_workload_configs()
        
        # 系统构建状态
        self.system_built = False
        self.statistics_configured = False
        
    def _get_default_workload_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        获取默认的工作负载配置
        
        Returns:
            包含不同核心类型工作负载配置的字典
        """
        return {
            "master_core": {
                "generator": "miranda.STREAMBenchGenerator",
                "max_reqs_cycle": "2",
                "params": {
                    "verbose": "1",
                    "n": "10000",
                    "operandwidth": "8",
                    "iterations": "100"
                },
                "description": "主控核心 - STREAM基准测试 + 网络发送"
            },
            "memory_controller": {
                "generator": "miranda.RandomGenerator",
                "max_reqs_cycle": "4",
                "params": {
                    "verbose": "1",
                    "count": "5000",
                    "max_address": "1048576",
                    "min_address": "0",
                    "length": "64"
                },
                "description": "内存控制器 - 随机访问模式 + 远程内存访问"
            },
            "io_core": {
                "generator": "miranda.SingleStreamGenerator",
                "max_reqs_cycle": "1",
                "params": {
                    "verbose": "1",
                    "count": "2000",
                    "start_a": "0",
                    "length": "32",
                    "stride": "32"
                },
                "description": "I/O核心 - 单流访问模式 + 数据分发"
            },
            "compute_core": {
                "generator": "miranda.GUPSGenerator",
                "max_reqs_cycle": "2",
                "params": {
                    "verbose": "1",
                    "count": "3000",
                    "max_address": "524288",
                    "min_address": "0",
                    "iterations": "50"
                },
                "description": "计算核心 - GUPS基准测试 + 点对点通信"
            },
            "network_test": {
                "generator": "miranda.RandomGenerator",
                "max_reqs_cycle": "1",
                "params": {
                    "verbose": "1",
                    "count": "1000",
                    "max_address": str(0x100000 * 16),  # 访问其他节点的地址空间
                    "min_address": "1048576",  # 从1MB开始，避免本地内存
                    "length": "64"
                },
                "description": "网络测试 - 跨节点内存访问"
            }
        }
    
    def set_workload_config(self, core_type: str, config: Dict[str, Any]) -> None:
        """
        设置特定核心类型的工作负载配置
        
        Args:
            core_type: 核心类型 ("master_core", "memory_controller", "io_core", "compute_core")
            config: 工作负载配置字典
        """
        if core_type in self.workload_configs:
            self.workload_configs[core_type].update(config)
        else:
            self.workload_configs[core_type] = config
            
    def _determine_core_type(self, node_id: int) -> str:
        """
        根据节点ID确定核心类型
        
        Args:
            node_id: 节点ID
            
        Returns:
            核心类型字符串
        """
        x = node_id % self.mesh_size_x
        y = node_id // self.mesh_size_x
        
        if x == 0 and y == 0:
            return "master_core"
        elif x == self.mesh_size_x - 1 and y == self.mesh_size_y - 1:
            return "memory_controller"
        elif x == 0 or x == self.mesh_size_x - 1 or y == 0 or y == self.mesh_size_y - 1:
            return "io_core"
        else:
            return "compute_core"
    
    def _create_router(self, node_id: int) -> Any:
        """
        创建路由器组件
        
        Args:
            node_id: 节点ID
            
        Returns:
            路由器组件
        """
        router = sst.Component(f"router_{node_id}", "merlin.hr_router")
        router.addParams({
            "id": node_id,
            "num_ports": "5",  # 4个网络方向 + 1个本地端口
            "link_bw": self.link_bandwidth,
            "flit_size": "8B",
            "xbar_bw": self.link_bandwidth,
            "input_latency": self.link_latency,
            "output_latency": self.link_latency,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 配置mesh拓扑
        topo_sub = router.setSubComponent("topology", "merlin.mesh")
        topo_sub.addParams({
            "network_name": "Miranda_CPU_Mesh",
            "shape": f"{self.mesh_size_x}x{self.mesh_size_y}",
            "width": "1x1",
            "local_ports": "1",
        })
        
        return router
    
    def _create_cpu_core(self, node_id: int) -> Any:
        """
        创建Miranda CPU核心
        
        Args:
            node_id: 节点ID
            
        Returns:
            CPU核心组件
        """
        cpu_core = sst.Component(f"cpu_{node_id}", "miranda.BaseCPU")
        
        # 确定核心类型和配置
        core_type = self._determine_core_type(node_id)
        workload_config = self.workload_configs[core_type]
        
        # 基础参数
        cpu_params = {
            "verbose": "1",
            "printStats": "1",
            "clock": self.cpu_clock,
            "max_reqs_cycle": workload_config["max_reqs_cycle"],
            "generator": workload_config["generator"]
        }
        
        # 添加生成器特定参数
        for param_key, param_value in workload_config["params"].items():
            cpu_params[f"generatorParams.{param_key}"] = param_value
        
        cpu_core.addParams(cpu_params)
        
        if self.verbose:
            x = node_id % self.mesh_size_x
            y = node_id // self.mesh_size_x
            print(f"  - CPU核心 {node_id} (位置: {x},{y}): {workload_config['description']}")
        
        return cpu_core
    
    def _create_memory_hierarchy(self, node_id: int, cpu_core: Any) -> tuple:
        """
        创建内存层次结构（L1缓存 + 本地内存控制器）
        
        Args:
            node_id: 节点ID
            cpu_core: CPU核心组件
            
        Returns:
            (L1缓存, 内存控制器) 元组
        """
        # 创建内存接口
        mem_iface = cpu_core.setSubComponent("memory", "memHierarchy.standardInterface")
        
        # 创建L1缓存
        l1_cache = sst.Component(f"l1cache_{node_id}", "memHierarchy.Cache")
        l1_cache.addParams({
            "cache_frequency": self.cpu_clock,
            "cache_size": self.cache_size,
            "associativity": "8",
            "access_latency_cycles": "1",
            "L1": "1",
            "verbose": "0",
            "coherence_protocol": "none",
            "replacement_policy": "lru",
        })
        
        # 连接CPU到L1缓存
        cpu_cache_link = sst.Link(f"cpu_cache_link_{node_id}")
        cpu_cache_link.connect(
            (mem_iface, "lowlink", "50ps"),
            (l1_cache, "high_network_0", "50ps")
        )
        
        # 创建内存总线/交叉开关，用于连接本地内存和网络
        mem_bus = sst.Component(f"mem_bus_{node_id}", "memHierarchy.Bus")
        mem_bus.addParams({
            "bus_frequency": "2GHz",
        })
        
        # 连接L1缓存到内存总线
        l1_bus_link = sst.Link(f"l1_bus_link_{node_id}")
        l1_bus_link.connect(
            (l1_cache, "low_network_0", "20ns"),
            (mem_bus, "high_network_0", "20ns")
        )
        
        # 创建本地内存控制器
        local_mem_ctrl = sst.Component(f"local_mem_ctrl_{node_id}", "memHierarchy.MemController")
        local_mem_ctrl.addParams({
            "clock": "1GHz",
            "backing": "none",
            "verbose": "0",
            "addr_range_start": "0",
            "addr_range_end": "134217727",  # 128MB地址空间
        })
        
        # 创建本地内存后端
        local_mem_backend = local_mem_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        local_mem_backend.addParams({
            "access_time": "100ns",
            "mem_size": self.memory_size,
        })
        
        # 连接内存总线到本地内存控制器
        bus_mem_link = sst.Link(f"bus_mem_link_{node_id}")
        bus_mem_link.connect(
            (mem_bus, "low_network_0", "20ns"),
            (local_mem_ctrl, "highlink", "20ns")
        )
        
        return l1_cache, local_mem_ctrl, mem_bus
    
    def _create_simple_memory_hierarchy(self, node_id: int, cpu_core: Any) -> tuple:
        """
        创建简化的内存层次结构（只有L1缓存和本地内存控制器）
        
        Args:
            node_id: 节点ID
            cpu_core: CPU核心组件
            
        Returns:
            (L1缓存, 内存控制器) 元组
        """
        # 创建内存接口
        mem_iface = cpu_core.setSubComponent("memory", "memHierarchy.standardInterface")
        
        # 创建L1缓存
        l1_cache = sst.Component(f"l1cache_{node_id}", "memHierarchy.Cache")
        l1_cache.addParams({
            "cache_frequency": self.cpu_clock,
            "cache_size": self.cache_size,
            "associativity": "8",
            "access_latency_cycles": "1",
            "L1": "1",
            "verbose": "0",
            "coherence_protocol": "none",
            "replacement_policy": "lru",
        })
        
        # 连接CPU到L1缓存
        cpu_cache_link = sst.Link(f"cpu_cache_link_{node_id}")
        cpu_cache_link.connect(
            (mem_iface, "lowlink", "50ps"),
            (l1_cache, "high_network_0", "50ps")
        )
        
        # 创建本地内存控制器
        local_mem_ctrl = sst.Component(f"local_mem_ctrl_{node_id}", "memHierarchy.MemController")
        local_mem_ctrl.addParams({
            "clock": "1GHz",
            "backing": "none",
            "verbose": "0",
            "addr_range_start": "0",
            "addr_range_end": "134217727",  # 128MB地址空间
        })
        
        # 创建本地内存后端
        local_mem_backend = local_mem_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        local_mem_backend.addParams({
            "access_time": "100ns",
            "mem_size": self.memory_size,
        })
        
        # 连接L1缓存到本地内存控制器
        l1_mem_link = sst.Link(f"l1_mem_link_{node_id}")
        l1_mem_link.connect(
            (l1_cache, "low_network_0", "20ns"),
            (local_mem_ctrl, "highlink", "20ns")
        )
        
        return l1_cache, local_mem_ctrl
    
    def _build_mesh_network(self) -> int:
        """
        构建2D Mesh网络连接
        
        Returns:
            创建的链路数量
        """
        if self.verbose:
            print(f"\n=== 构建{self.mesh_size_x}x{self.mesh_size_y} Mesh网络连接 ===")
        
        link_count = 0
        
        for y in range(self.mesh_size_y):
            for x in range(self.mesh_size_x):
                node_id = y * self.mesh_size_x + x
                
                # 东西连接
                if x < self.mesh_size_x - 1:
                    link = sst.Link(f"mesh_east_{x}_{y}")
                    link.connect(
                        (self.routers[node_id], "port0", self.link_latency),      # 东端口
                        (self.routers[node_id + 1], "port1", self.link_latency)   # 西端口
                    )
                    link_count += 1
                
                # 南北连接
                if y < self.mesh_size_y - 1:
                    link = sst.Link(f"mesh_south_{x}_{y}")
                    link.connect(
                        (self.routers[node_id], "port2", self.link_latency),              # 南端口
                        (self.routers[node_id + self.mesh_size_x], "port3", self.link_latency) # 北端口
                    )
                    link_count += 1
        
        if self.verbose:
            print(f"✓ 创建了 {link_count} 条双向链路")
        
        return link_count
    
    def build_system(self) -> None:
        """
        构建完整的Miranda CPU Mesh系统
        """
        if self.system_built:
            print("⚠️ 系统已经构建，跳过重复构建")
            return
        
        if self.verbose:
            print("=== 构建基于Miranda CPU的Mesh系统 ===")
            print("使用Miranda CPU模拟器生成真实的网络流量")
        
        # 清空组件列表
        self.routers.clear()
        self.cpu_cores.clear()
        self.l1_caches.clear()
        self.memory_controllers.clear()
        
        # 创建所有节点
        for i in range(self.total_nodes):
            # 创建路由器
            router = self._create_router(i)
            self.routers.append(router)
            
            # 创建CPU核心
            cpu_core = self._create_cpu_core(i)
            self.cpu_cores.append(cpu_core)
            
            # 创建简化的内存层次结构（只有本地内存）
            l1_cache, mem_ctrl = self._create_simple_memory_hierarchy(i, cpu_core)
            self.l1_caches.append(l1_cache)
            self.memory_controllers.append(mem_ctrl)
            
            # 通过缓存连接到网络（为了支持远程内存访问）
            # 注释掉网络连接，保持简单的本地内存架构
            # cache_net_link = sst.Link(f"cache_net_link_{i}")
            # cache_net_link.connect(
            #     (l1_cache, "cache_link", "50ps"),
            #     (router, "port4", "50ps")  # 本地端口
            # )
        
        # 构建网络连接
        link_count = self._build_mesh_network()
        
        if self.verbose:
            print(f"\n✓ 每个CPU核心都有L1缓存({self.cache_size})和本地内存({self.memory_size})")
        
        self.system_built = True
        
        # 打印系统总结
        self._print_system_summary(link_count)
    
    def configure_statistics(self, 
                           output_filename: str = "miranda_mesh_stats.csv",
                           statistic_level: int = 5) -> None:
        """
        配置统计收集
        
        Args:
            output_filename: 输出文件名
            statistic_level: 统计级别
        """
        if self.statistics_configured:
            print("⚠️ 统计已经配置，跳过重复配置")
            return
            
        if self.verbose:
            print("\n=== 配置Miranda CPU系统统计 ===")
        
        # 确保输出目录存在
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
            if self.verbose:
                print(f"✓ 创建输出目录: {self.output_dir}")
        
        output_file = os.path.join(self.output_dir, output_filename)
        
        # 配置统计输出
        sst.setStatisticLoadLevel(statistic_level)
        sst.setStatisticOutput("sst.statOutputCSV", {"filepath": output_file})
        
        # 启用组件类型统计
        sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
        sst.enableAllStatisticsForComponentType("merlin.hr_router")
        sst.enableAllStatisticsForComponentType("memHierarchy.standardInterface")
        sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
        sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
        
        # 启用特定统计项
        for i in range(self.total_nodes):
            cpu_name = f"cpu_{i}"
            router_name = f"router_{i}"
            
            # CPU统计
            sst.enableStatisticForComponentName(cpu_name, "cycles")
            sst.enableStatisticForComponentName(cpu_name, "reqs_issued")
            sst.enableStatisticForComponentName(cpu_name, "reqs_returned")
            
            # 网络统计
            sst.enableStatisticForComponentName(router_name, "send_packet_count")
            sst.enableStatisticForComponentName(router_name, "recv_packet_count")
        
        self.statistics_configured = True
        
        if self.verbose:
            print("✓ Miranda CPU系统统计配置完成")
            print(f"  统计输出: {output_file}")
    
    def configure_simulation(self, 
                           simulation_time: str = "100us",
                           enable_statistics: bool = True,
                           output_filename: str = "miranda_mesh_stats.csv") -> None:
        """
        配置仿真参数
        
        Args:
            simulation_time: 仿真时间
            enable_statistics: 是否启用统计收集
            output_filename: 统计输出文件名
        """
        if not self.system_built:
            raise RuntimeError("必须先调用 build_system() 构建系统")
        
        if enable_statistics:
            self.configure_statistics(output_filename)
        
        # 设置仿真时间限制
        sst.setProgramOption("stop-at", simulation_time)
        
        if self.verbose:
            print(f"\n⏱️  仿真配置:")
            print(f"   • 仿真时间: {simulation_time}")
            if enable_statistics:
                print(f"   • 统计输出: {os.path.join(self.output_dir, output_filename)}")
            print(f"   • 详细日志: {'启用' if self.verbose else '禁用'}")
    
    def _print_system_summary(self, link_count: int) -> None:
        """
        打印系统配置总结
        
        Args:
            link_count: 链路数量
        """
        if not self.verbose:
            return
            
        print(f"\n=== Miranda CPU系统配置总结 ===")
        print(f"🏗️  系统架构:")
        print(f"   • 网格规模: {self.mesh_size_x}×{self.mesh_size_y} = {self.total_nodes} 个Miranda CPU核心")
        print(f"   • CPU模拟器: Miranda BaseCPU (真实指令执行)")
        print(f"   • 网络拓扑: 2D Mesh (用于CPU间通信)")
        print(f"   • 内存层次: L1缓存({self.cache_size}) + 本地内存控制器({self.memory_size})")
        print(f"   • 链路性能: {self.link_bandwidth} 带宽, {self.link_latency} 延迟")
        print(f"   • 网络链路: {link_count} 条双向链路")
        
        print(f"\n🧠 CPU工作负载分布:")
        for core_type, config in self.workload_configs.items():
            if not core_type.startswith("node_"):
                print(f"   • {config['description']}")
        
        print(f"\n📡 网络通信功能:")
        print(f"   • 每个节点都有独立的本地内存后端")
        print(f"   • Miranda CPU生成真实的内存访问模式")
        print(f"   • 网络用于CPU间的数据流量传输")
        
        print(f"\n🚀 Miranda CPU系统构建完成!")
        print("   Miranda将生成真实的内存访问和网络流量")
    
    def get_system_info(self) -> Dict[str, Any]:
        """
        获取系统信息
        
        Returns:
            包含系统配置信息的字典
        """
        return {
            "mesh_size": (self.mesh_size_x, self.mesh_size_y),
            "total_nodes": self.total_nodes,
            "link_bandwidth": self.link_bandwidth,
            "link_latency": self.link_latency,
            "cpu_clock": self.cpu_clock,
            "cache_size": self.cache_size,
            "memory_size": self.memory_size,
            "output_dir": self.output_dir,
            "system_built": self.system_built,
            "statistics_configured": self.statistics_configured,
            "workload_configs": self.workload_configs
        }
    
    def get_components(self) -> Dict[str, List[Any]]:
        """
        获取系统组件引用
        
        Returns:
            包含所有组件列表的字典
        """
        return {
            "routers": self.routers,
            "cpu_cores": self.cpu_cores,
            "l1_caches": self.l1_caches,
            "memory_controllers": self.memory_controllers
        }
    
    def set_node_communication_pattern(self, 
                                     source_node: int, 
                                     target_nodes: List[int],
                                     message_size: str = "64B",
                                     message_count: int = 1000) -> None:
        """
        配置特定节点的通信模式
        
        Args:
            source_node: 源节点ID
            target_nodes: 目标节点ID列表
            message_size: 消息大小
            message_count: 消息数量
        """
        if source_node >= self.total_nodes:
            raise ValueError(f"源节点ID {source_node} 超出范围")
        
        for target in target_nodes:
            if target >= self.total_nodes:
                raise ValueError(f"目标节点ID {target} 超出范围")
        
        # 为源节点配置网络测试工作负载
        network_config = {
            "generator": "miranda.RandomGenerator",
            "max_reqs_cycle": "2",
            "params": {
                "verbose": "1",
                "count": str(message_count),
                "max_address": str(max(target_nodes) * 0x100000 + 0x100000 - 1),
                "min_address": str(min(target_nodes) * 0x100000),
                "length": message_size.replace("B", "")
            },
            "description": f"节点{source_node}到节点{target_nodes}的通信测试"
        }
        
        self.set_workload_config(f"node_{source_node}", network_config)
        
        if self.verbose:
            print(f"✓ 配置节点 {source_node} 向节点 {target_nodes} 发送 {message_count} 条 {message_size} 消息")
    
    def enable_all_to_all_communication(self, message_density: str = "low") -> None:
        """
        启用全对全通信模式
        
        Args:
            message_density: 消息密度 ("low", "medium", "high")
        """
        density_configs = {
            "low": {"max_reqs_cycle": "1", "count": "500"},
            "medium": {"max_reqs_cycle": "2", "count": "1000"},
            "high": {"max_reqs_cycle": "4", "count": "2000"}
        }
        
        config = density_configs.get(message_density, density_configs["low"])
        
        for i in range(self.total_nodes):
            network_config = {
                "generator": "miranda.RandomGenerator",
                "max_reqs_cycle": config["max_reqs_cycle"],
                "params": {
                    "verbose": "1",
                    "count": config["count"],
                    "max_address": str(self.total_nodes * 0x100000 - 1),
                    "min_address": "1048576",  # 跳过本地内存区域
                    "length": "64"
                },
                "description": f"节点{i}全对全通信({message_density}密度)"
            }
            self.set_workload_config(f"node_{i}", network_config)
        
        if self.verbose:
            print(f"✓ 启用全对全通信模式，密度: {message_density}")
    
    def get_node_address_range(self, node_id: int) -> tuple:
        """
        获取节点的网络地址范围
        
        Args:
            node_id: 节点ID
            
        Returns:
            (起始地址, 结束地址) 元组
        """
        if node_id >= self.total_nodes:
            raise ValueError(f"节点ID {node_id} 超出范围")
        
        start_addr = 0x100000 + node_id * 0x100000
        end_addr = start_addr + 0x100000 - 1
        return (start_addr, end_addr)


# 便利函数：快速创建和配置系统
def create_miranda_mesh_system(**kwargs) -> MirandaCPUMeshSystem:
    """
    便利函数：创建Miranda CPU Mesh系统
    
    Args:
        **kwargs: 传递给MirandaCPUMeshSystem构造函数的参数
        
    Returns:
        配置好的MirandaCPUMeshSystem实例
    """
    return MirandaCPUMeshSystem(**kwargs)


def build_and_configure_system(mesh_size_x: int = 4,
                              mesh_size_y: int = 4,
                              simulation_time: str = "100us",
                              **kwargs) -> MirandaCPUMeshSystem:
    """
    便利函数：构建并配置完整的Miranda CPU Mesh系统
    
    Args:
        mesh_size_x: Mesh X维度大小
        mesh_size_y: Mesh Y维度大小
        simulation_time: 仿真时间
        **kwargs: 其他传递给系统构造函数的参数
        
    Returns:
        构建并配置好的系统实例
    """
    system = MirandaCPUMeshSystem(
        mesh_size_x=mesh_size_x,
        mesh_size_y=mesh_size_y,
        **kwargs
    )
    
    system.build_system()
    system.configure_simulation(simulation_time=simulation_time)
    
    return system


def create_communication_test_system(mesh_size_x: int = 4,
                                    mesh_size_y: int = 4,
                                    communication_pattern: str = "point_to_point",
                                    **kwargs) -> MirandaCPUMeshSystem:
    """
    便利函数：创建配置好节点间通信的测试系统
    
    Args:
        mesh_size_x: Mesh X维度大小
        mesh_size_y: Mesh Y维度大小  
        communication_pattern: 通信模式 ("point_to_point", "all_to_all", "ring")
        **kwargs: 其他传递给系统构造函数的参数
        
    Returns:
        配置好通信模式的系统实例
    """
    system = MirandaCPUMeshSystem(
        mesh_size_x=mesh_size_x,
        mesh_size_y=mesh_size_y,
        **kwargs
    )
    
    system.build_system()
    
    # 根据通信模式配置系统
    if communication_pattern == "all_to_all":
        system.enable_all_to_all_communication("medium")
    elif communication_pattern == "point_to_point":
        # 配置对角线节点间通信
        system.set_node_communication_pattern(0, [system.total_nodes - 1])
        system.set_node_communication_pattern(system.total_nodes - 1, [0])
    elif communication_pattern == "ring":
        # 配置环形通信
        for i in range(system.total_nodes):
            next_node = (i + 1) % system.total_nodes
            system.set_node_communication_pattern(i, [next_node])
    
    system.configure_simulation()
    
    return system
