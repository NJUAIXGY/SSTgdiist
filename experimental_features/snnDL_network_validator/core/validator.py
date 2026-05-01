#!/usr/bin/env python3
"""
SnnDL网络验证器

统一的网络验证接口，协调各层验证器进行综合验证
"""

import os
import sys
from typing import Dict, List, Tuple, Optional, Any

# 导入拓扑信息和转换器
from .topology_extractor import TopologyInfo
from .converter import GraphLibConverter


class NetworkValidator:
    """
    SnnDL网络验证器主类
    
    协调物理层、逻辑层、数据层验证器进行综合网络验证
    """
    
    def __init__(self):
        """初始化验证器"""
        self.converter = GraphLibConverter()
        
    def validate_physical_layer(self, physical_topology: TopologyInfo) -> Dict[str, Any]:
        """
        验证物理层拓扑 (mesh路由器网络)
        
        Args:
            physical_topology: 物理层拓扑信息
            
        Returns:
            物理层验证结果
        """
        print("🔍 验证物理层拓扑...")
        
        if not physical_topology.edges:
            return {'valid': False, 'error': '物理层拓扑为空'}
        
        mesh_size = physical_topology.metadata.get('mesh_size', 4)
        
        # 使用GraphLib算法验证mesh拓扑
        mesh_results = self.converter.analyze_mesh_topology(
            physical_topology.edges, mesh_size)
        
        # 构建验证结果
        results = {
            'valid': True,
            'connectivity': mesh_results['connectivity']['is_connected'],
            'regularity': mesh_results['regularity']['is_regular'],
            'symmetry': mesh_results['symmetry']['is_symmetric'],
            'diameter': mesh_results.get('mesh_diameter', 0),
            'average_degree': mesh_results['degree_analysis']['avg_degree'],
            'total_edges': mesh_results['degree_analysis']['total_edges'],
            'errors': [],
            'warnings': []
        }
        
        # 收集错误和警告
        if not results['connectivity']:
            results['valid'] = False
            results['errors'].append("物理网络不连通")
        
        if not results['regularity']:
            results['errors'].extend(mesh_results['regularity']['errors'][:5])  # 最多显示5个错误
            if len(mesh_results['regularity']['errors']) > 5:
                results['warnings'].append(f"还有{len(mesh_results['regularity']['errors']) - 5}个规律性错误")
        
        if not results['symmetry']:
            results['errors'].extend(mesh_results['symmetry']['errors'][:5])
            if len(mesh_results['symmetry']['errors']) > 5:
                results['warnings'].append(f"还有{len(mesh_results['symmetry']['errors']) - 5}个对称性错误")
        
        print(f"  ✅ 物理层验证完成: {'通过' if results['valid'] else '失败'}")
        return results
    
    def validate_logical_layer(self, logical_topology: TopologyInfo) -> Dict[str, Any]:
        """
        验证逻辑层拓扑 (分层神经网络)
        
        Args:
            logical_topology: 逻辑层拓扑信息
            
        Returns:
            逻辑层验证结果
        """
        print("🔍 验证逻辑层拓扑...")
        
        if not logical_topology.edges:
            return {'valid': False, 'error': '逻辑层拓扑为空'}
        
        layers = logical_topology.metadata.get('layers', {})
        layer_connections = logical_topology.metadata.get('layer_connections', [])
        
        # 验证分层结构
        layer_validation = self._validate_layer_structure(layers, layer_connections)
        
        # 验证前馈连接
        feedforward_validation = self._validate_feedforward_connections(
            logical_topology.edges, layers)
        
        # 检测异常连接
        anomaly_detection = self._detect_logical_anomalies(
            logical_topology.edges, layers)
        
        # 使用GraphLib验证连通性
        vertex_num = len(logical_topology.nodes)
        basic_properties = self.converter.validate_graph_properties(
            logical_topology.edges, vertex_num)
        
        # 构建验证结果
        results = {
            'valid': True,
            'layer_structure_valid': layer_validation['valid'],
            'feedforward_valid': feedforward_validation['valid'],
            'connectivity': basic_properties['connectivity']['is_connected'],
            'total_logical_connections': len(layer_connections),
            'anomalies': anomaly_detection,
            'errors': [],
            'warnings': []
        }
        
        # 收集错误
        results['errors'].extend(layer_validation.get('errors', []))
        results['errors'].extend(feedforward_validation.get('errors', []))
        
        if len(anomaly_detection) > 0:
            results['warnings'].append(f"检测到{len(anomaly_detection)}个逻辑连接异常")
        
        results['valid'] = len(results['errors']) == 0
        
        print(f"  ✅ 逻辑层验证完成: {'通过' if results['valid'] else '失败'}")
        return results
    
    def validate_data_layer(self, data_topology: TopologyInfo) -> Dict[str, Any]:
        """
        验证数据层拓扑 (权重矩阵连接)
        
        Args:
            data_topology: 数据层拓扑信息
            
        Returns:
            数据层验证结果
        """
        print("🔍 验证数据层拓扑...")
        
        if not data_topology.edges:
            return {'valid': False, 'error': '数据层拓扑为空'}
        
        connection_patterns = data_topology.metadata.get('connection_patterns', {})
        
        # 验证权重连接模式
        pattern_validation = self._validate_connection_patterns(connection_patterns)
        
        # 验证权重分布
        weight_validation = self._validate_weight_distribution(data_topology.edges)
        
        # 使用GraphLib验证图性质
        vertex_num = len(data_topology.nodes)
        basic_properties = self.converter.validate_graph_properties(
            data_topology.edges, vertex_num)
        
        # 构建验证结果
        results = {
            'valid': True,
            'pattern_valid': pattern_validation['valid'],
            'weight_distribution_valid': weight_validation['valid'],
            'connectivity': basic_properties['connectivity']['is_connected'],
            'total_data_connections': data_topology.metadata.get('total_connections', 0),
            'feedforward_connections': data_topology.metadata.get('feedforward_connections', 0),
            'backward_connections': data_topology.metadata.get('backward_connections', 0),
            'avg_connection_strength': data_topology.metadata.get('avg_connection_strength', 0.0),
            'errors': [],
            'warnings': []
        }
        
        # 收集错误和警告
        results['errors'].extend(pattern_validation.get('errors', []))
        results['errors'].extend(weight_validation.get('errors', []))
        results['warnings'].extend(weight_validation.get('warnings', []))
        
        # 检查反向连接异常
        if results['backward_connections'] > 0:
            results['warnings'].append(f"检测到{results['backward_connections']}个反向连接")
        
        results['valid'] = len(results['errors']) == 0
        
        print(f"  ✅ 数据层验证完成: {'通过' if results['valid'] else '失败'}")
        return results
    
    def validate_cross_layer_consistency(self, physical_topology: TopologyInfo,
                                       logical_topology: TopologyInfo,
                                       data_topology: TopologyInfo) -> Dict[str, Any]:
        """
        验证跨层一致性
        
        Args:
            physical_topology: 物理层拓扑
            logical_topology: 逻辑层拓扑  
            data_topology: 数据层拓扑
            
        Returns:
            跨层一致性验证结果
        """
        print("🔍 验证跨层一致性...")
        
        results = {
            'valid': True,
            'node_mapping_consistent': True,
            'logical_data_consistent': True,
            'routing_efficient': True,
            'errors': [],
            'warnings': []
        }
        
        # 1. 节点映射一致性检查
        physical_nodes = set(physical_topology.nodes)
        logical_nodes = set(logical_topology.nodes)
        data_nodes = set(data_topology.nodes)
        
        if not (physical_nodes == logical_nodes == data_nodes):
            results['node_mapping_consistent'] = False
            results['errors'].append("三层拓扑的节点映射不一致")
        
        # 2. 逻辑-数据层一致性检查
        logical_connections = logical_topology.metadata.get('total_logical_connections', 0)
        data_feedforward_connections = data_topology.metadata.get('feedforward_connections', 0)
        
        if logical_connections != data_feedforward_connections:
            results['logical_data_consistent'] = False
            results['warnings'].append(
                f"逻辑连接数({logical_connections})与数据前馈连接数({data_feedforward_connections})不匹配")
        
        # 3. 路由效率检查
        mesh_size = physical_topology.metadata.get('mesh_size', 4)
        max_physical_distance = 2 * (mesh_size - 1)  # mesh最大距离
        
        # 检查数据层连接是否在合理的物理距离内
        inefficient_routes = self._check_routing_efficiency(
            physical_topology.edges, data_topology.edges, mesh_size)
        
        if inefficient_routes:
            results['routing_efficient'] = False
            results['warnings'].extend(inefficient_routes[:3])  # 最多显示3个警告
        
        results['valid'] = len(results['errors']) == 0
        
        print(f"  ✅ 跨层一致性验证完成: {'通过' if results['valid'] else '失败'}")
        return results
    
    def _validate_layer_structure(self, layers: Dict[str, List[int]], 
                                 layer_connections: List) -> Dict[str, Any]:
        """验证层结构定义"""
        results = {'valid': True, 'errors': []}
        
        expected_layers = ['INPUT_LAYER', 'HIDDEN_LAYER_1', 'HIDDEN_LAYER_2', 'OUTPUT_LAYER']
        
        for layer_name in expected_layers:
            if layer_name not in layers:
                results['errors'].append(f"缺少层定义: {layer_name}")
                results['valid'] = False
            elif not layers[layer_name]:
                results['errors'].append(f"层{layer_name}为空")
                results['valid'] = False
        
        return results
    
    def _validate_feedforward_connections(self, edges: Dict[int, List], 
                                        layers: Dict[str, List[int]]) -> Dict[str, Any]:
        """验证前馈连接"""
        results = {'valid': True, 'errors': []}
        
        # 构建节点到层的映射
        node_to_layer = {}
        layer_order = ['INPUT_LAYER', 'HIDDEN_LAYER_1', 'HIDDEN_LAYER_2', 'OUTPUT_LAYER']
        
        for layer_name, nodes in layers.items():
            for node in nodes:
                node_to_layer[node] = layer_name
        
        # 检查前馈连接规律
        expected_connections = [
            ('INPUT_LAYER', 'HIDDEN_LAYER_1'),
            ('HIDDEN_LAYER_1', 'HIDDEN_LAYER_2'),
            ('HIDDEN_LAYER_2', 'OUTPUT_LAYER')
        ]
        
        for source_layer, target_layer in expected_connections:
            source_nodes = layers.get(source_layer, [])
            target_nodes = layers.get(target_layer, [])
            
            # 检查每个目标节点是否有来自源层的连接
            for target_node in target_nodes:
                has_connection_from_source = False
                
                if target_node in edges:
                    for edge in edges[target_node]:
                        source_node = edge.dst_v
                        if source_node in source_nodes:
                            has_connection_from_source = True
                            break
                
                if not has_connection_from_source:
                    results['errors'].append(
                        f"目标节点{target_node}({target_layer})缺少来自{source_layer}的连接")
                    results['valid'] = False
        
        return results
    
    def _detect_logical_anomalies(self, edges: Dict[int, List], 
                                 layers: Dict[str, List[int]]) -> List[str]:
        """检测逻辑连接异常"""
        anomalies = []
        
        node_to_layer = {}
        layer_order = ['INPUT_LAYER', 'HIDDEN_LAYER_1', 'HIDDEN_LAYER_2', 'OUTPUT_LAYER']
        
        for layer_name, nodes in layers.items():
            for node in nodes:
                node_to_layer[node] = layer_name
        
        # 检测反向连接
        for target_node, edge_list in edges.items():
            target_layer = node_to_layer.get(target_node, 'UNKNOWN')
            
            for edge in edge_list:
                source_node = edge.dst_v
                source_layer = node_to_layer.get(source_node, 'UNKNOWN')
                
                try:
                    source_idx = layer_order.index(source_layer)
                    target_idx = layer_order.index(target_layer)
                    
                    if target_idx <= source_idx:
                        anomalies.append(
                            f"异常连接: {source_node}({source_layer}) -> {target_node}({target_layer})")
                except ValueError:
                    anomalies.append(
                        f"未知层连接: {source_node}({source_layer}) -> {target_node}({target_layer})")
        
        return anomalies
    
    def _validate_connection_patterns(self, patterns: Dict) -> Dict[str, Any]:
        """验证连接模式"""
        results = {'valid': True, 'errors': []}
        
        feedforward = patterns.get('feedforward_connections', [])
        backward = patterns.get('backward_connections', [])
        
        # 检查是否有反向连接
        if backward:
            results['errors'].append(f"检测到{len(backward)}个反向连接，这可能表示权重配置错误")
            results['valid'] = False
        
        # 检查前馈连接数量是否合理
        if len(feedforward) < 40:  # 对于4x4分层网络，期望至少40个前馈连接
            results['errors'].append(f"前馈连接数量过少({len(feedforward)})，可能存在权重加载问题")
            results['valid'] = False
        
        return results
    
    def _validate_weight_distribution(self, edges: Dict[int, List]) -> Dict[str, Any]:
        """验证权重分布"""
        results = {'valid': True, 'errors': [], 'warnings': []}
        
        all_weights = []
        for edge_list in edges.values():
            for edge in edge_list:
                all_weights.append(edge.weight)
        
        if not all_weights:
            results['errors'].append("没有有效的权重数据")
            results['valid'] = False
            return results
        
        # 统计权重分布
        avg_weight = sum(all_weights) / len(all_weights)
        max_weight = max(all_weights)
        min_weight = min(all_weights)
        
        # 检查异常权重
        if max_weight > 1000.0:
            results['warnings'].append(f"检测到异常大权重: {max_weight:.2f}")
        
        if min_weight < 0:
            results['warnings'].append(f"检测到负权重: {min_weight:.2f}")
        
        if avg_weight < 0.1:
            results['warnings'].append(f"平均权重过小: {avg_weight:.4f}")
        
        return results
    
    def _check_routing_efficiency(self, physical_edges: Dict[int, List],
                                 data_edges: Dict[int, List], mesh_size: int) -> List[str]:
        """检查路由效率"""
        inefficient_routes = []
        
        # 计算物理距离矩阵
        vertex_num = mesh_size * mesh_size
        
        for target_node, edge_list in data_edges.items():
            for edge in edge_list:
                source_node = edge.dst_v
                
                # 计算物理距离
                physical_distance = self._calculate_mesh_distance(source_node, target_node, mesh_size)
                
                # 检查是否超过合理距离
                if physical_distance > mesh_size - 1:  # mesh上最远距离应该是mesh_size-1
                    inefficient_routes.append(
                        f"低效路由: PE{source_node}->PE{target_node} (物理距离: {physical_distance})")
        
        return inefficient_routes
    
    def _calculate_mesh_distance(self, node1: int, node2: int, mesh_size: int) -> int:
        """计算mesh网络中两节点的曼哈顿距离"""
        x1, y1 = node1 % mesh_size, node1 // mesh_size
        x2, y2 = node2 % mesh_size, node2 // mesh_size
        
        return abs(x1 - x2) + abs(y1 - y2)


if __name__ == "__main__":
    # 测试验证器
    print("🔍 测试网络验证器...")
    
    # 这里可以添加简单的测试用例
    validator = NetworkValidator()
    print("✅ 网络验证器初始化完成")