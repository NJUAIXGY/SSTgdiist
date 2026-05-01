#!/usr/bin/env python3
"""
SnnDL网络拓扑提取器

从SnnDL配置文件和权重文件提取三层网络拓扑:
1. 物理层: 4x4 mesh路由器连接
2. 逻辑层: 分层神经网络连接
3. 数据层: 权重矩阵连接模式
"""

import os
import re
import ast
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

# 导入权重解析器
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from parsers.weight_parser import WeightFileParser, Edge


@dataclass
class TopologyInfo:
    """拓扑信息数据结构"""
    nodes: List[int]
    edges: Dict[int, List[Edge]]
    metadata: Dict[str, Any]


class TopologyExtractor:
    """
    SnnDL网络拓扑提取器
    
    从SnnDL配置文件和数据文件中提取多层网络拓扑结构
    """
    
    def __init__(self):
        """初始化拓扑提取器"""
        self.weight_parser = WeightFileParser()
        
        # 默认4x4分类网络配置
        self.default_config = {
            'mesh_size': 4,
            'total_nodes': 16,
            'neurons_per_pe': 16,
            'layer_definitions': {
                'INPUT_LAYER': list(range(0, 4)),
                'HIDDEN_LAYER_1': list(range(4, 8)),
                'HIDDEN_LAYER_2': list(range(8, 12)),
                'OUTPUT_LAYER': list(range(12, 16))
            }
        }
    
    def extract_physical_topology(self, config_path: str) -> TopologyInfo:
        """
        提取物理层拓扑 (4x4 mesh路由器连接)
        
        Args:
            config_path: SnnDL配置文件路径
            
        Returns:
            物理层拓扑信息
        """
        # 解析配置文件获取mesh参数
        config = self._parse_config_file(config_path)
        mesh_size = config.get('mesh_size', 4)
        total_nodes = mesh_size * mesh_size
        
        # 构建mesh连接拓扑
        edge_map = {}
        
        for node_id in range(total_nodes):
            edge_map[node_id] = []
            
            # 计算2D网格坐标
            x, y = node_id % mesh_size, node_id // mesh_size
            
            # 东西连接 (East-West)
            if x < mesh_size - 1:  # East连接
                east_node = y * mesh_size + (x + 1)
                edge_map[node_id].append(Edge(east_node, 1.0))
            if x > 0:  # West连接
                west_node = y * mesh_size + (x - 1)
                edge_map[node_id].append(Edge(west_node, 1.0))
            
            # 南北连接 (North-South)
            if y < mesh_size - 1:  # South连接
                south_node = (y + 1) * mesh_size + x
                edge_map[node_id].append(Edge(south_node, 1.0))
            if y > 0:  # North连接
                north_node = (y - 1) * mesh_size + x
                edge_map[node_id].append(Edge(north_node, 1.0))
        
        # 构建拓扑信息
        topology = TopologyInfo(
            nodes=list(range(total_nodes)),
            edges=edge_map,
            metadata={
                'topology_type': 'physical_mesh',
                'mesh_size': mesh_size,
                'total_nodes': total_nodes,
                'connectivity': 'mesh2d',
                'max_degree': 4,
                'avg_degree': self._calculate_average_degree(edge_map)
            }
        )
        
        return topology
    
    def extract_logical_topology(self, config_path: str) -> TopologyInfo:
        """
        提取逻辑层拓扑 (分层神经网络连接)
        
        Args:
            config_path: SnnDL配置文件路径
            
        Returns:
            逻辑层拓扑信息
        """
        config = self._parse_config_file(config_path)
        layer_definitions = config.get('layer_definitions', self.default_config['layer_definitions'])
        
        # 构建分层连接拓扑
        edge_map = {}
        layer_connections = []
        
        # 定义标准前馈连接
        layer_pairs = [
            ('INPUT_LAYER', 'HIDDEN_LAYER_1'),
            ('HIDDEN_LAYER_1', 'HIDDEN_LAYER_2'), 
            ('HIDDEN_LAYER_2', 'OUTPUT_LAYER')
        ]
        
        # 为每个节点初始化边列表
        all_nodes = []
        for layer_nodes in layer_definitions.values():
            all_nodes.extend(layer_nodes)
            
        for node in all_nodes:
            edge_map[node] = []
        
        # 构建层间连接
        for source_layer_name, target_layer_name in layer_pairs:
            source_nodes = layer_definitions.get(source_layer_name, [])
            target_nodes = layer_definitions.get(target_layer_name, [])
            
            for target_node in target_nodes:
                for source_node in source_nodes:
                    # 使用均匀权重表示逻辑连接
                    edge_map[target_node].append(Edge(source_node, 1.0))
                    layer_connections.append((source_layer_name, target_layer_name, source_node, target_node))
        
        # 构建拓扑信息
        topology = TopologyInfo(
            nodes=all_nodes,
            edges=edge_map, 
            metadata={
                'topology_type': 'logical_neural',
                'layers': layer_definitions,
                'layer_connections': layer_connections,
                'feedforward_only': True,
                'total_logical_connections': len(layer_connections)
            }
        )
        
        return topology
    
    def extract_data_topology(self, config_path: str) -> TopologyInfo:
        """
        提取数据层拓扑 (权重矩阵连接)
        
        Args:
            config_path: SnnDL配置文件路径
            
        Returns:
            数据层拓扑信息 
        """
        config = self._parse_config_file(config_path)
        
        # 获取权重文件目录
        weights_dir = self._extract_weights_directory(config_path)
        if not weights_dir or not os.path.exists(weights_dir):
            # 尝试默认路径
            default_weights_dir = "/home/anarchy/SST/optimized_classification_package/weights"
            if os.path.exists(default_weights_dir):
                weights_dir = default_weights_dir
            else:
                raise ValueError(f"权重文件目录不存在: {weights_dir}, 也找不到默认目录: {default_weights_dir}")
        
        # 使用权重解析器提取连接
        weight_matrices = self.weight_parser.parse_all_weight_files(weights_dir)
        pe_connections = self.weight_parser.extract_pe_connections(weight_matrices, threshold=0.01)
        connection_patterns = self.weight_parser.analyze_connection_patterns(pe_connections)
        
        # 计算连接统计信息
        total_connections = sum(len(edges) for edges in pe_connections.values())
        connection_strengths = []
        for edges in pe_connections.values():
            for edge in edges:
                connection_strengths.append(edge.weight)
        
        avg_connection_strength = sum(connection_strengths) / len(connection_strengths) if connection_strengths else 0.0
        
        # 构建拓扑信息
        topology = TopologyInfo(
            nodes=list(range(len(weight_matrices))),
            edges=pe_connections,
            metadata={
                'topology_type': 'data_weights',
                'weights_directory': weights_dir,
                'total_connections': total_connections,
                'avg_connection_strength': avg_connection_strength,
                'connection_patterns': connection_patterns,
                'feedforward_connections': len(connection_patterns['feedforward_connections']),
                'backward_connections': len(connection_patterns['backward_connections']),
                'intra_layer_connections': len(connection_patterns['intra_layer_connections']),
                'skip_connections': len(connection_patterns['skip_connections'])
            }
        )
        
        return topology
    
    def _parse_config_file(self, config_path: str) -> Dict:
        """
        解析SnnDL配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置参数字典
        """
        config = self.default_config.copy()
        
        if not os.path.exists(config_path):
            print(f"⚠️ 配置文件不存在: {config_path}，使用默认配置")
            return config
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取关键配置参数
            mesh_size_match = re.search(r'MESH_SIZE\s*=\s*(\d+)', content)
            if mesh_size_match:
                config['mesh_size'] = int(mesh_size_match.group(1))
                config['total_nodes'] = config['mesh_size'] ** 2
            
            neurons_per_pe_match = re.search(r'NEURONS_PER_PE\s*=\s*(\d+)', content)
            if neurons_per_pe_match:
                config['neurons_per_pe'] = int(neurons_per_pe_match.group(1))
            
            # 提取层定义
            layer_patterns = {
                'INPUT_LAYER': r'INPUT_LAYER\s*=\s*(.+)',
                'HIDDEN_LAYER_1': r'HIDDEN_LAYER_1\s*=\s*(.+)',
                'HIDDEN_LAYER_2': r'HIDDEN_LAYER_2\s*=\s*(.+)',
                'OUTPUT_LAYER': r'OUTPUT_LAYER\s*=\s*(.+)'
            }
            
            for layer_name, pattern in layer_patterns.items():
                match = re.search(pattern, content)
                if match:
                    try:
                        layer_def = ast.literal_eval(match.group(1))
                        config['layer_definitions'][layer_name] = layer_def
                    except:
                        pass  # 保持默认值
            
        except Exception as e:
            print(f"⚠️ 解析配置文件失败: {e}，使用默认配置")
        
        return config
    
    def _extract_weights_directory(self, config_path: str) -> Optional[str]:
        """
        从配置文件中提取权重文件目录
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            权重文件目录路径
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 查找权重目录相关配置
            weights_dir_match = re.search(r'weights_dir\s*=\s*["\']([^"\']+)["\']', content)
            if weights_dir_match:
                return weights_dir_match.group(1)
            
            # 查找权重文件路径模式
            weights_file_match = re.search(r'weights_file.*["\']([^"\']+)["\']', content)
            if weights_file_match:
                weights_file = weights_file_match.group(1)
                return os.path.dirname(weights_file)
            
            # 查找目录定义
            dirname_match = re.search(r'os\.path\.dirname.*weights["\')]', content)
            if dirname_match:
                # 基于配置文件路径推断权重目录
                config_dir = os.path.dirname(config_path)
                possible_weights_dirs = [
                    os.path.join(config_dir, 'weights'),
                    os.path.join(os.path.dirname(config_dir), 'weights'),
                    os.path.join(config_dir, '..', 'weights')
                ]
                
                for weights_dir in possible_weights_dirs:
                    abs_weights_dir = os.path.abspath(weights_dir)
                    if os.path.exists(abs_weights_dir):
                        return abs_weights_dir
            
            # 默认推断：配置文件同级或上级的weights目录
            config_dir = os.path.dirname(config_path)
            default_weights_dir = os.path.join(os.path.dirname(config_dir), 'weights')
            if os.path.exists(default_weights_dir):
                return default_weights_dir
                
        except Exception as e:
            print(f"⚠️ 提取权重目录失败: {e}")
        
        return None
    
    def _calculate_average_degree(self, edge_map: Dict[int, List[Edge]]) -> float:
        """计算平均度数"""
        if not edge_map:
            return 0.0
        
        total_degree = sum(len(edges) for edges in edge_map.values())
        return total_degree / len(edge_map)
    
    def extract_all_topologies(self, config_path: str) -> Dict[str, TopologyInfo]:
        """
        提取所有层的拓扑结构
        
        Args:
            config_path: SnnDL配置文件路径
            
        Returns:
            包含所有拓扑的字典
        """
        print(f"🔍 提取SnnDL网络拓扑: {config_path}")
        
        topologies = {}
        
        try:
            # 提取物理层拓扑
            print("  📡 提取物理层拓扑 (mesh路由器)...")
            topologies['physical'] = self.extract_physical_topology(config_path)
            print(f"    ✅ 物理节点: {len(topologies['physical'].nodes)}, 连接: {sum(len(edges) for edges in topologies['physical'].edges.values())}")
            
            # 提取逻辑层拓扑  
            print("  🧠 提取逻辑层拓扑 (神经网络层)...")
            topologies['logical'] = self.extract_logical_topology(config_path)
            print(f"    ✅ 逻辑连接: {topologies['logical'].metadata['total_logical_connections']}")
            
            # 提取数据层拓扑
            print("  💾 提取数据层拓扑 (权重矩阵)...")
            topologies['data'] = self.extract_data_topology(config_path)
            print(f"    ✅ 数据连接: {topologies['data'].metadata['total_connections']}")
            print(f"    📊 前馈: {topologies['data'].metadata['feedforward_connections']}, 反向: {topologies['data'].metadata['backward_connections']}")
            
        except Exception as e:
            print(f"❌ 拓扑提取失败: {e}")
            raise
        
        print("✅ 拓扑提取完成")
        return topologies


# 便捷函数
def extract_snnDL_topologies(config_path: str) -> Dict[str, TopologyInfo]:
    """
    便捷函数：提取SnnDL所有拓扑层
    
    Args:
        config_path: SnnDL配置文件路径
        
    Returns:
        拓扑字典
    """
    extractor = TopologyExtractor()
    return extractor.extract_all_topologies(config_path)


if __name__ == "__main__":
    # 测试拓扑提取器
    test_config = "/home/anarchy/SST/optimized_classification_package/scripts/test_classification_4x4.py"
    
    if os.path.exists(test_config):
        print("🔍 测试拓扑提取器...")
        
        extractor = TopologyExtractor()
        topologies = extractor.extract_all_topologies(test_config)
        
        print(f"\n📊 拓扑提取结果:")
        for topo_name, topo_info in topologies.items():
            print(f"  {topo_name}:")
            print(f"    节点数: {len(topo_info.nodes)}")
            print(f"    边数: {sum(len(edges) for edges in topo_info.edges.values())}")
            print(f"    类型: {topo_info.metadata.get('topology_type', 'unknown')}")
            
    else:
        print(f"❌ 测试配置文件不存在: {test_config}")