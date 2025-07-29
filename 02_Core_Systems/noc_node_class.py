"""
NoC节点封装类
用于构建可复用的片上网络节点组件
"""

import sst

class NoCNode:
    """
    片上网络节点类
    封装了CPU、缓存、内存控制器和路由器的完整节点
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
            is_memory_node: 是否为共享内存节点
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
        self.router = None
        self.cpu = None
        self.l1_cache = None
        self.mem_nic = None  # 网络接口
        self.mem_ctrl = None  # 仅内存节点拥有
        self.mem_backend = None  # 仅内存节点拥有
        
        # 连接链路
        self.cpu_cache_link = None
        self.cache_network_link = None  # 缓存到网络的链路
        
        # 创建节点组件
        self._create_components()
        if not self.is_memory_node:
            self._configure_workload()
        self._connect_components()
    
    def _create_components(self):
        """创建节点的所有组件"""
        # 创建路由器
        self.router = sst.Component(f"router_{self.node_id}", "merlin.hr_router")
        self.router.addParams({
            "id": self.node_id,
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
        topo_sub = self.router.setSubComponent("topology", "merlin.mesh")
        topo_sub.addParams({
            "network_name": "Miranda_CPU_Mesh",
            "shape": f"{self.mesh_size_x}x{self.mesh_size_y}",
            "width": "1x1",
            "local_ports": "1",
        })
        
        if self.is_memory_node:
            # 内存节点：只创建内存控制器，不创建CPU和缓存
            self._create_memory_controller()
        else:
            # 计算节点：创建CPU和L1缓存，以及网络接口
            self._create_cpu_and_cache()
            self._create_network_interface()
    
    def _create_cpu_and_cache(self):
        """创建CPU和L1缓存（仅计算节点）"""
        # 创建Miranda CPU核心
        self.cpu = sst.Component(f"cpu_{self.node_id}", "miranda.BaseCPU")
        
        # 创建L1缓存
        self.l1_cache = sst.Component(f"l1cache_{self.node_id}", "memHierarchy.Cache")
        self.l1_cache.addParams({
            "cache_frequency": "2.4GHz",
            "cache_size": "32KiB",
            "associativity": "8",
            "access_latency_cycles": "1",
            "L1": "1",
            "verbose": "0",
            "coherence_protocol": "none",
            "replacement_policy": "lru",
        })
    
    def _create_network_interface(self):
        """创建网络接口（仅计算节点）"""
        # 为L1缓存配置网络接口子组件
        self.mem_nic = self.l1_cache.setSubComponent("memlink", "memHierarchy.MemNIC")
        self.mem_nic.addParams({
            "group": "1",
            "verbose": "0",
            "network_bw": self.link_bandwidth,
            "min_packet_size": "8B",
            "max_packet_size": "64B",
        })
    
    def _create_memory_controller(self):
        """创建共享内存控制器（仅内存节点）"""
        # 创建内存控制器
        self.mem_ctrl = sst.Component(f"shared_mem_ctrl_{self.node_id}", "memHierarchy.MemController")
        self.mem_ctrl.addParams({
            "clock": "1GHz",
            "backing": "none",
            "verbose": "0",
            "addr_range_start": "0",
            "addr_range_end": str(512 * 1024 * 1024 - 1),  # 512MB共享地址空间
        })
        
        # 创建内存后端
        self.mem_backend = self.mem_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        self.mem_backend.addParams({
            "access_time": "100ns",
            "mem_size": "512MiB",
        })
        
        # 为内存控制器配置网络接口
        self.mem_nic = self.mem_ctrl.setSubComponent("memlink", "memHierarchy.MemNIC")
        self.mem_nic.addParams({
            "group": "2",
            "verbose": "0",
            "network_bw": self.link_bandwidth,
            "min_packet_size": "8B",
            "max_packet_size": "64B",
        })
    
    def _configure_workload(self):
        """根据节点位置配置不同的工作负载（仅计算节点）"""
        # 计算每个节点的内存访问范围，实现跨节点通信
        total_nodes = self.mesh_size_x * self.mesh_size_y
        memory_per_node = 512 * 1024 * 1024 // total_nodes  # 512MB / 节点数
        base_addr = self.node_id * memory_per_node
        
        if self.x == 0 and self.y == 0:  # 主控核心
            self.cpu.addParams({
                "verbose": "1",
                "printStats": "1",
                "clock": "2.4GHz",
                "max_reqs_cycle": "2",
                "generator": "miranda.STREAMBenchGenerator",
                "generatorParams.verbose": "1",
                "generatorParams.n": "10000",
                "generatorParams.operandwidth": "8",
                "generatorParams.iterations": "50",
                "generatorParams.start_a": str(base_addr),
                "generatorParams.start_b": str(base_addr + memory_per_node // 3),
                "generatorParams.start_c": str(base_addr + 2 * memory_per_node // 3),
            })
            self.workload_type = "主控核心 - STREAM基准测试（跨节点访问）"
            
        elif self.x == self.mesh_size_x-1 and self.y == self.mesh_size_y-1:  # 分布式访问核心
            # 访问其他节点的内存区域
            remote_base = ((self.node_id + total_nodes // 2) % total_nodes) * memory_per_node
            self.cpu.addParams({
                "verbose": "1",
                "printStats": "1",
                "clock": "2.4GHz",
                "max_reqs_cycle": "3",
                "generator": "miranda.RandomGenerator",
                "generatorParams.verbose": "1",
                "generatorParams.count": "5000",
                "generatorParams.max_address": str(remote_base + memory_per_node - 1),
                "generatorParams.min_address": str(remote_base),
                "generatorParams.length": "64",
            })
            self.workload_type = "分布式访问核心 - 远程随机访问"
            
        elif (self.x == 0 or self.x == self.mesh_size_x-1 or 
              self.y == 0 or self.y == self.mesh_size_y-1):  # 边界通信核心
            # 边界节点访问相邻节点的内存
            neighbor_id = (self.node_id + 1) % total_nodes
            neighbor_base = neighbor_id * memory_per_node
            self.cpu.addParams({
                "verbose": "1",
                "printStats": "1",
                "clock": "2.4GHz",
                "max_reqs_cycle": "2",
                "generator": "miranda.SingleStreamGenerator",
                "generatorParams.verbose": "1",
                "generatorParams.count": "3000",
                "generatorParams.start_a": str(neighbor_base),
                "generatorParams.length": "32",
                "generatorParams.stride": "32",
            })
            self.workload_type = "边界通信核心 - 邻居节点访问"
            
        else:  # 计算核心
            # 访问多个节点的内存区域，模拟分布式计算
            multi_node_base = base_addr
            multi_node_range = min(memory_per_node * 2, 512 * 1024 * 1024 - multi_node_base)
            self.cpu.addParams({
                "verbose": "1",
                "printStats": "1",
                "clock": "2.4GHz",
                "max_reqs_cycle": "2",
                "generator": "miranda.GUPSGenerator",
                "generatorParams.verbose": "1",
                "generatorParams.count": "4000",
                "generatorParams.max_address": str(multi_node_base + multi_node_range - 1),
                "generatorParams.min_address": str(multi_node_base),
                "generatorParams.iterations": "30",
            })
            self.workload_type = "分布式计算核心 - 多节点GUPS测试"
    
    def _connect_components(self):
        """连接节点内部组件"""
        if self.is_memory_node:
            # 内存节点：只连接内存控制器到路由器
            self.cache_network_link = sst.Link(f"mem_network_link_{self.node_id}")
            self.cache_network_link.connect(
                (self.mem_nic, "port", "20ns"),
                (self.router, "port4", "20ns")  # 本地端口
            )
        else:
            # 计算节点：连接CPU -> L1缓存 -> 网络
            # 创建内存接口
            mem_iface = self.cpu.setSubComponent("memory", "memHierarchy.standardInterface")
            
            # 连接CPU到L1缓存
            self.cpu_cache_link = sst.Link(f"cpu_cache_link_{self.node_id}")
            self.cpu_cache_link.connect(
                (mem_iface, "lowlink", "50ps"),
                (self.l1_cache, "high_network_0", "50ps")
            )
            
            # 连接L1缓存到网络（通过MemNIC）
            self.cache_network_link = sst.Link(f"cache_network_link_{self.node_id}")
            self.cache_network_link.connect(
                (self.mem_nic, "port", "20ns"),
                (self.router, "port4", "20ns")  # 本地端口
            )
    
    def connect_to_router(self, other_router, port_self, port_other, link_name):
        """
        连接当前节点的路由器到另一个路由器
        
        Args:
            other_router: 目标路由器组件
            port_self: 当前路由器使用的端口
            port_other: 目标路由器使用的端口
            link_name: 链路名称
        """
        link = sst.Link(link_name)
        link.connect(
            (self.router, port_self, self.link_latency),
            (other_router, port_other, self.link_latency)
        )
        return link
    
    def get_router(self):
        """获取路由器组件引用"""
        return self.router
    
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
                "workload": "共享内存控制器 - 512MB"
            }
        else:
            return {
                "node_id": self.node_id,
                "position": (self.x, self.y),
                "workload": getattr(self, 'workload_type', '未配置工作负载')
            }
    
    def enable_statistics(self):
        """启用节点的统计收集"""
        if not self.is_memory_node:
            # CPU统计
            sst.enableStatisticForComponentName(f"cpu_{self.node_id}", "cycles")
            sst.enableStatisticForComponentName(f"cpu_{self.node_id}", "reqs_issued")
            sst.enableStatisticForComponentName(f"cpu_{self.node_id}", "reqs_returned")
            
            # 缓存统计
            sst.enableStatisticForComponentName(f"l1cache_{self.node_id}", "cache_hits")
            sst.enableStatisticForComponentName(f"l1cache_{self.node_id}", "cache_misses")
        else:
            # 内存控制器统计
            sst.enableStatisticForComponentName(f"shared_mem_ctrl_{self.node_id}", "requests_received")
            sst.enableStatisticForComponentName(f"shared_mem_ctrl_{self.node_id}", "requests_completed")
        
        # 网络统计（所有节点）
        sst.enableStatisticForComponentName(f"router_{self.node_id}", "send_packet_count")
        sst.enableStatisticForComponentName(f"router_{self.node_id}", "recv_packet_count")
        sst.enableStatisticForComponentName(f"router_{self.node_id}", "buffer_occupancy")


class NoCMesh:
    """
    NoC Mesh网络类
    管理整个mesh网络的构建和配置，支持共享内存通信
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
            memory_nodes: 共享内存节点位置列表，默认为角落节点
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
        self.links = []
        self.network_component = None
        
        # 创建网络组件
        self._create_network_component()
        # 创建所有节点
        self._create_nodes()
        # 构建mesh连接
        self._build_mesh_connections()
    
    def _create_network_component(self):
        """创建Merlin网络组件用于路由表配置"""
        self.network_component = sst.Component("network", "merlin.mesh")
        self.network_component.addParams({
            "network_name": "Miranda_CPU_Mesh",
            "shape": f"{self.mesh_size_x}x{self.mesh_size_y}",
            "width": "1x1",
            "local_ports": "1",
            "link_bw": self.link_bandwidth,
            "flit_size": "8B",
            "input_latency": self.link_latency,
            "output_latency": self.link_latency,
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
    
    def _create_nodes(self):
        """创建所有NoC节点"""
        print("=== 创建NoC节点 ===")
        
        compute_count = 0
        memory_count = 0
        
        for i in range(self.total_nodes):
            x = i % self.mesh_size_x
            y = i // self.mesh_size_x
            
            is_memory = i in self.memory_nodes
            
            node = NoCNode(i, x, y, self.mesh_size_x, self.mesh_size_y,
                          self.link_bandwidth, self.link_latency, is_memory)
            self.nodes.append(node)
            
            if is_memory:
                memory_count += 1
                print(f"  - 内存节点 {i} (位置: {x},{y}): 共享内存控制器 - 512MB")
            else:
                compute_count += 1
                info = node.get_info()
                print(f"  - 计算节点 {i} (位置: {x},{y}): {info['workload']}")
        
        print(f"✓ 总共创建 {compute_count} 个计算节点和 {memory_count} 个内存节点")
    
    def _build_mesh_connections(self):
        """构建mesh网络连接"""
        print("\n=== 构建Mesh网络连接 ===")
        
        link_count = 0
        for y in range(self.mesh_size_y):
            for x in range(self.mesh_size_x):
                node_id = y * self.mesh_size_x + x
                current_node = self.nodes[node_id]
                
                # 东西连接
                if x < self.mesh_size_x - 1:
                    east_node = self.nodes[node_id + 1]
                    link = current_node.connect_to_router(
                        east_node.get_router(),
                        "port0",  # 东端口
                        "port1",  # 西端口
                        f"mesh_east_{x}_{y}"
                    )
                    self.links.append(link)
                    link_count += 1
                
                # 南北连接
                if y < self.mesh_size_y - 1:
                    south_node = self.nodes[node_id + self.mesh_size_x]
                    link = current_node.connect_to_router(
                        south_node.get_router(),
                        "port2",  # 南端口
                        "port3",  # 北端口
                        f"mesh_south_{x}_{y}"
                    )
                    self.links.append(link)
                    link_count += 1
        
        print(f"✓ 创建了 {link_count} 条双向链路")
        
        # 配置内存地址映射
        self._configure_memory_mapping()
    
    def _configure_memory_mapping(self):
        """配置共享内存地址映射"""
        print("\n=== 配置共享内存地址映射 ===")
        
        memory_nodes = self.get_memory_nodes()
        if not memory_nodes:
            print("⚠️  警告: 没有找到内存节点!")
            return
        
        # 为每个内存节点分配地址范围
        total_memory = 512 * 1024 * 1024  # 512MB
        memory_per_node = total_memory // len(memory_nodes)
        
        for i, mem_node in enumerate(memory_nodes):
            start_addr = i * memory_per_node
            end_addr = start_addr + memory_per_node - 1
            
            # 更新内存控制器的地址范围
            mem_node.mem_ctrl.addParams({
                "addr_range_start": str(start_addr),
                "addr_range_end": str(end_addr),
            })
            
            print(f"  - 内存节点 {mem_node.node_id}: 地址范围 0x{start_addr:08x} - 0x{end_addr:08x}")
        
        print("✓ 内存地址映射配置完成")
    
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
    
    def enable_all_statistics(self):
        """启用所有节点的统计收集"""
        print("=== 启用统计收集 ===")
        
        # 启用组件类型统计
        sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
        sst.enableAllStatisticsForComponentType("merlin.hr_router")
        sst.enableAllStatisticsForComponentType("memHierarchy.standardInterface")
        sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
        sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
        
        # 启用每个节点的统计
        for node in self.nodes:
            node.enable_statistics()
        
        print("✓ 统计收集配置完成")
    
    def setup_statistics_output(self, output_path="/home/anarchy/SST/sst_output_data/noc_mesh_stats.csv"):
        """设置统计输出"""
        import os
        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"✓ 创建输出目录: {output_dir}")
        
        sst.setStatisticLoadLevel(5)
        sst.setStatisticOutput("sst.statOutputCSV", {"filepath": output_path})
        print(f"✓ 统计输出文件: {output_path}")
    
    def print_summary(self):
        """打印系统配置总结"""
        print(f"\n=== 共享内存NoC Mesh系统配置总结 ===")
        print(f"🏗️  系统架构:")
        print(f"   • 网格规模: {self.mesh_size_x}×{self.mesh_size_y} = {self.total_nodes} 个节点")
        print(f"   • CPU模拟器: Miranda BaseCPU (真实指令执行)")
        print(f"   • 网络拓扑: 2D Mesh with 共享内存")
        print(f"   • 内存架构: 分布式共享内存 (512MB总容量)")
        print(f"   • 链路性能: {self.link_bandwidth} 带宽, {self.link_latency} 延迟")
        
        compute_nodes = self.get_compute_nodes()
        memory_nodes = self.get_memory_nodes()
        
        print(f"\n🧠 节点分布:")
        print(f"   • 计算节点: {len(compute_nodes)} 个")
        print(f"   • 内存节点: {len(memory_nodes)} 个")
        
        print(f"\n📍 内存节点位置:")
        for node in memory_nodes:
            print(f"   • 节点 {node.node_id} (位置: {node.x},{node.y})")
        
        print(f"\n🔄 工作负载分布:")
        workload_summary = {}
        for node in compute_nodes:
            info = node.get_info()
            workload = info['workload']
            if workload not in workload_summary:
                workload_summary[workload] = 0
            workload_summary[workload] += 1
        
        for workload, count in workload_summary.items():
            print(f"   • {workload}: {count} 个节点")
            
        print(f"\n🌐 通信模式:")
        print(f"   • 跨节点内存访问: 启用")
        print(f"   • 内存地址映射: 分区式 (每节点 {512//self.total_nodes}MB)")
        print(f"   • 网络接口: MemNIC (memHierarchy.MemNIC)")
        print(f"   • 路由协议: Mesh XY路由")
    
    def create_communication_demo(self):
        """创建一个展示跨节点通信的演示配置"""
        print(f"\n=== 跨节点通信演示配置 ===")
        
        compute_nodes = self.get_compute_nodes()
        memory_nodes = self.get_memory_nodes()
        
        if len(compute_nodes) < 2:
            print("⚠️  需要至少2个计算节点来演示通信")
            return
        
        print(f"📡 通信场景:")
        print(f"   • 节点0 -> 访问远程节点的内存区域")
        print(f"   • 边界节点 -> 访问相邻节点内存")
        print(f"   • 中心节点 -> 跨多个节点的分布式访问")
        
        print(f"\n🔄 数据流向:")
        for i, node in enumerate(compute_nodes[:3]):
            if i == 0:
                target_info = "远程内存区域"
            elif node.x == 0 or node.y == 0:
                target_info = "相邻节点内存"
            else:
                target_info = "分布式多节点内存"
            print(f"   • 计算节点 {node.node_id} -> {target_info}")
        
        print(f"\n📊 预期网络流量:")
        print(f"   • 总网络包数: 预计 10K-50K 包")
        print(f"   • 平均跳数: 1-3 跳 (取决于源目距离)")
        print(f"   • 缓存命中率: 20-40% (跨节点访问)")
        
        return True
