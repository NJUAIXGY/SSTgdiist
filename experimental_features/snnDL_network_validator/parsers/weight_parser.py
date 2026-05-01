#!/usr/bin/env python3
"""
SnnDL权重文件解析器

解析SnnDL二进制权重文件，提取连接矩阵和拓扑结构
支持4x4分类网络的权重格式解析
"""

import os
import struct
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

# 定义Edge类（简化版，避免依赖GraphLib的networkx依赖）
@dataclass
class Edge:
    """图边结构"""
    dst_v: int
    weight: float


@dataclass 
class WeightStatistics:
    """权重统计信息"""
    total_weights: int
    non_zero_weights: int
    zero_ratio: float
    max_weight: float
    min_weight: float
    mean_weight: float
    std_dev: float


class WeightFileParser:
    """
    SnnDL权重文件解析器
    
    解析二进制权重文件格式，提取PE级连接拓扑
    """
    
    def __init__(self, neurons_per_pe=16, total_pes=16):
        """
        初始化解析器
        
        Args:
            neurons_per_pe: 每个PE的神经元数量 (默认16)
            total_pes: 总PE数量 (默认16)
        """
        self.neurons_per_pe = neurons_per_pe
        self.total_pes = total_pes
        self.global_neurons = neurons_per_pe * total_pes
        
        # 4x4分类网络层定义
        self.layer_definitions = {
            'INPUT_LAYER': list(range(0, 4)),      # PE 0-3
            'HIDDEN_LAYER_1': list(range(4, 8)),   # PE 4-7  
            'HIDDEN_LAYER_2': list(range(8, 12)),  # PE 8-11
            'OUTPUT_LAYER': list(range(12, 16))    # PE 12-15
        }
        
    def parse_single_weight_file(self, weight_file: str) -> np.ndarray:
        """
        解析单个权重文件
        
        Args:
            weight_file: 权重文件路径
            
        Returns:
            权重矩阵 [target_neuron_local, source_neuron_global]
        """
        if not os.path.exists(weight_file):
            raise FileNotFoundError(f"权重文件不存在: {weight_file}")
            
        weights = []
        try:
            with open(weight_file, 'rb') as f:
                while True:
                    data = f.read(4)  # 4字节float
                    if not data:
                        break
                    weight = struct.unpack('f', data)[0]
                    weights.append(weight)
        except Exception as e:
            raise ValueError(f"解析权重文件失败 {weight_file}: {e}")
        
        # 验证权重数量
        expected_size = self.neurons_per_pe * self.global_neurons
        if len(weights) != expected_size:
            print(f"⚠️ 权重文件大小异常: 期望{expected_size}, 实际{len(weights)}")
        
        # 重构为矩阵: [target_neuron_local][source_neuron_global]
        weight_matrix = np.array(weights).reshape(self.neurons_per_pe, self.global_neurons)
        
        return weight_matrix
    
    def parse_all_weight_files(self, weights_dir: str) -> Dict[int, np.ndarray]:
        """
        解析所有PE的权重文件
        
        Args:
            weights_dir: 权重文件目录
            
        Returns:
            PE ID -> 权重矩阵的字典
        """
        weight_matrices = {}
        
        for pe_id in range(self.total_pes):
            weight_file = os.path.join(weights_dir, f"classification_weights_pe_{pe_id}.bin")
            
            if os.path.exists(weight_file):
                try:
                    weight_matrix = self.parse_single_weight_file(weight_file)
                    weight_matrices[pe_id] = weight_matrix
                    print(f"✅ 解析PE{pe_id}权重文件: {weight_matrix.shape}")
                except Exception as e:
                    print(f"❌ PE{pe_id}权重文件解析失败: {e}")
            else:
                print(f"⚠️ PE{pe_id}权重文件不存在: {weight_file}")
        
        return weight_matrices
    
    def extract_pe_connections(self, weight_matrices: Dict[int, np.ndarray], 
                              threshold: float = 0.01) -> Dict[int, List[Edge]]:
        """
        从权重矩阵提取PE级连接拓扑
        
        Args:
            weight_matrices: PE权重矩阵字典
            threshold: 权重阈值，低于此值的连接将被忽略
            
        Returns:
            PE级连接图 {target_pe: [Edge(source_pe, weight), ...]}
        """
        pe_connections = {}
        
        for target_pe, matrix in weight_matrices.items():
            pe_connections[target_pe] = []
            
            # 聚合PE级权重
            for source_pe in range(self.total_pes):
                source_start = source_pe * self.neurons_per_pe
                source_end = source_start + self.neurons_per_pe
                
                # 计算PE间总连接强度 (所有神经元连接权重之和)
                pe_weight = np.sum(np.abs(matrix[:, source_start:source_end]))
                
                if pe_weight > threshold:
                    pe_connections[target_pe].append(Edge(source_pe, pe_weight))
        
        return pe_connections
    
    def analyze_connection_patterns(self, pe_connections: Dict[int, List[Edge]]) -> Dict:
        """
        分析连接模式
        
        Args:
            pe_connections: PE连接拓扑
            
        Returns:
            连接模式分析结果
        """
        patterns = {
            'feedforward_connections': [],  # 前馈连接
            'backward_connections': [],     # 反向连接 
            'intra_layer_connections': [],  # 层内连接
            'skip_connections': []          # 跳层连接
        }
        
        layer_map = {}
        for layer_name, nodes in self.layer_definitions.items():
            for node in nodes:
                layer_map[node] = layer_name
        
        for target_pe, edges in pe_connections.items():
            target_layer = layer_map.get(target_pe, 'UNKNOWN')
            
            for edge in edges:
                source_pe = edge.dst_v
                source_layer = layer_map.get(source_pe, 'UNKNOWN')
                
                # 分类连接类型
                if self._is_feedforward_connection(source_layer, target_layer):
                    patterns['feedforward_connections'].append((source_pe, target_pe, edge.weight))
                elif self._is_backward_connection(source_layer, target_layer):
                    patterns['backward_connections'].append((source_pe, target_pe, edge.weight))
                elif source_layer == target_layer:
                    patterns['intra_layer_connections'].append((source_pe, target_pe, edge.weight))
                else:
                    patterns['skip_connections'].append((source_pe, target_pe, edge.weight))
        
        return patterns
    
    def _is_feedforward_connection(self, source_layer: str, target_layer: str) -> bool:
        """判断是否为正常前馈连接"""
        layer_order = ['INPUT_LAYER', 'HIDDEN_LAYER_1', 'HIDDEN_LAYER_2', 'OUTPUT_LAYER']
        
        try:
            source_idx = layer_order.index(source_layer)
            target_idx = layer_order.index(target_layer)
            return target_idx == source_idx + 1
        except ValueError:
            return False
    
    def _is_backward_connection(self, source_layer: str, target_layer: str) -> bool:
        """判断是否为异常反向连接"""
        layer_order = ['INPUT_LAYER', 'HIDDEN_LAYER_1', 'HIDDEN_LAYER_2', 'OUTPUT_LAYER']
        
        try:
            source_idx = layer_order.index(source_layer)
            target_idx = layer_order.index(target_layer)
            return target_idx < source_idx
        except ValueError:
            return False
    
    def compute_weight_statistics(self, weight_matrices: Dict[int, np.ndarray]) -> Dict[int, WeightStatistics]:
        """
        计算权重统计信息
        
        Args:
            weight_matrices: 权重矩阵字典
            
        Returns:
            每个PE的权重统计信息
        """
        statistics = {}
        
        for pe_id, matrix in weight_matrices.items():
            weights = matrix.flatten()
            non_zero_weights = weights[np.abs(weights) > 1e-6]
            
            stats = WeightStatistics(
                total_weights=len(weights),
                non_zero_weights=len(non_zero_weights),
                zero_ratio=(len(weights) - len(non_zero_weights)) / len(weights),
                max_weight=float(np.max(weights)),
                min_weight=float(np.min(weights)),
                mean_weight=float(np.mean(non_zero_weights)) if len(non_zero_weights) > 0 else 0.0,
                std_dev=float(np.std(non_zero_weights)) if len(non_zero_weights) > 0 else 0.0
            )
            
            statistics[pe_id] = stats
        
        return statistics
    
    def validate_weight_consistency(self, weight_matrices: Dict[int, np.ndarray]) -> Dict:
        """
        验证权重一致性
        
        Args:
            weight_matrices: 权重矩阵字典
            
        Returns:
            验证结果
        """
        results = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # 检查权重文件完整性
        missing_pes = []
        for pe_id in range(self.total_pes):
            if pe_id not in weight_matrices:
                missing_pes.append(pe_id)
        
        if missing_pes:
            results['errors'].append(f"缺失PE权重文件: {missing_pes}")
            results['valid'] = False
        
        # 检查权重分布异常
        statistics = self.compute_weight_statistics(weight_matrices)
        
        for pe_id, stats in statistics.items():
            if stats.zero_ratio > 0.99:
                results['warnings'].append(f"PE{pe_id}: 权重过于稀疏 (零权重比例: {stats.zero_ratio:.2%})")
            
            if stats.max_weight > 100.0:
                results['warnings'].append(f"PE{pe_id}: 存在异常大权重 (最大值: {stats.max_weight:.2f})")
            
            if stats.std_dev < 0.001 and stats.mean_weight > 0:
                results['warnings'].append(f"PE{pe_id}: 权重过于均匀 (标准差: {stats.std_dev:.6f})")
        
        return results


# 便捷函数
def parse_snnDL_weights(weights_dir: str, threshold: float = 0.01) -> Dict:
    """
    便捷函数：解析SnnDL权重文件并提取拓扑
    
    Args:
        weights_dir: 权重文件目录
        threshold: 连接阈值
        
    Returns:
        包含权重矩阵、PE连接和统计信息的字典
    """
    parser = WeightFileParser()
    
    # 解析权重文件
    weight_matrices = parser.parse_all_weight_files(weights_dir)
    
    # 提取PE连接
    pe_connections = parser.extract_pe_connections(weight_matrices, threshold)
    
    # 分析连接模式
    patterns = parser.analyze_connection_patterns(pe_connections)
    
    # 计算统计信息
    statistics = parser.compute_weight_statistics(weight_matrices)
    
    # 验证一致性
    validation = parser.validate_weight_consistency(weight_matrices)
    
    return {
        'weight_matrices': weight_matrices,
        'pe_connections': pe_connections,
        'connection_patterns': patterns,
        'statistics': statistics,
        'validation': validation
    }


if __name__ == "__main__":
    # 测试权重解析器
    weights_dir = "/home/anarchy/SST/optimized_classification_package/weights"
    
    if os.path.exists(weights_dir):
        print("🔍 测试权重文件解析器...")
        result = parse_snnDL_weights(weights_dir)
        
        print(f"\n📊 解析结果:")
        print(f"  成功解析权重矩阵: {len(result['weight_matrices'])}个PE")
        print(f"  提取PE连接: {len(result['pe_connections'])}个PE")
        print(f"  前馈连接数: {len(result['connection_patterns']['feedforward_connections'])}")
        print(f"  反向连接数: {len(result['connection_patterns']['backward_connections'])}")
        print(f"  层内连接数: {len(result['connection_patterns']['intra_layer_connections'])}")
        
        if result['validation']['valid']:
            print("✅ 权重文件验证通过")
        else:
            print("❌ 权重文件验证失败:")
            for error in result['validation']['errors']:
                print(f"    {error}")
    else:
        print(f"❌ 权重文件目录不存在: {weights_dir}")