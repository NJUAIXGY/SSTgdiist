#!/usr/bin/env python3
"""
GraphLib转换器

将SnnDL拓扑数据转换为GraphLib兼容格式，并提供验证算法接口
"""

import os
import sys
from typing import Dict, List, Tuple, Optional, Any

# 导入GraphLib (处理依赖问题)
sys.path.append('/home/anarchy/SST/GraphLib')

# 定义简化的GraphLib接口类 (避免networkx依赖)
from dataclasses import dataclass

@dataclass
class Edge:
    """图边结构"""
    dst_v: int  
    weight: float

class GraphLibConverter:
    """
    SnnDL到GraphLib格式转换器
    
    将SnnDL拓扑结构转换为GraphLib兼容的数据格式
    并提供GraphLib验证算法的封装接口
    """
    
    def __init__(self):
        """初始化转换器"""
        self.MAX_INT = 9999999
    
    def convert_topology_to_graphlib(self, topology_edges: Dict[int, List[Edge]]) -> Dict[int, List[Edge]]:
        """
        转换拓扑结构为GraphLib格式
        
        Args:
            topology_edges: SnnDL拓扑边字典
            
        Returns:
            GraphLib兼容的边字典
        """
        # 当前SnnDL使用的Edge格式已经兼容GraphLib
        return topology_edges
    
    def create_random_graph_equivalent(self, edges: Dict[int, List[Edge]], vertex_num: int) -> Dict:
        """
        创建等价的RandomGraph结构
        
        Args:
            edges: 边字典
            vertex_num: 顶点数量
            
        Returns:
            RandomGraph等价结构
        """
        edge_count = sum(len(edge_list) for edge_list in edges.values())
        
        graph_data = {
            'vertex_num': vertex_num,
            'edge_num': edge_count,
            'edge_map': edges
        }
        
        return graph_data
    
    def run_bfs_validation(self, vertex_num: int, edge_map: Dict[int, List[Edge]], 
                          root: int) -> Tuple[Dict[int, Tuple[int, int]], bool]:
        """
        运行BFS算法进行连通性验证
        
        Args:
            vertex_num: 顶点数量
            edge_map: 边映射
            root: 根节点
            
        Returns:
            BFS树结果和验证状态
        """
        # 实现简化的BFS算法
        bfs_tree = {}
        queue = [root]
        visited = [False] * vertex_num
        visited[root] = True
        bfs_tree[root] = (0, root)  # (level, parent)
        current_level = 0
        
        while queue:
            next_queue = []
            
            for node in queue:
                if node in edge_map:
                    for edge in edge_map[node]:
                        neighbor = edge.dst_v
                        if neighbor < vertex_num and not visited[neighbor]:
                            visited[neighbor] = True
                            bfs_tree[neighbor] = (current_level + 1, node)
                            next_queue.append(neighbor)
            
            queue = next_queue
            current_level += 1
            
            # 防止无限循环
            if current_level > vertex_num:
                break
        
        # 检查连通性
        connected_nodes = len(bfs_tree)
        is_connected = connected_nodes == vertex_num
        
        return bfs_tree, is_connected
    
    def run_sssp_validation(self, vertex_num: int, edge_map: Dict[int, List[Edge]], 
                           root: int) -> Tuple[List[float], bool]:
        """
        运行最短路径算法
        
        Args:
            vertex_num: 顶点数量
            edge_map: 边映射
            root: 根节点
            
        Returns:
            距离数组和验证状态
        """
        # 使用简化的Dijkstra算法
        distances = [float('inf')] * vertex_num
        distances[root] = 0.0
        visited = [False] * vertex_num
        
        for _ in range(vertex_num):
            # 找到未访问节点中距离最小的
            min_dist = float('inf')
            min_node = -1
            
            for i in range(vertex_num):
                if not visited[i] and distances[i] < min_dist:
                    min_dist = distances[i]
                    min_node = i
            
            if min_node == -1:
                break
                
            visited[min_node] = True
            
            # 更新邻居距离
            if min_node in edge_map:
                for edge in edge_map[min_node]:
                    neighbor = edge.dst_v
                    if neighbor < vertex_num:
                        new_dist = distances[min_node] + edge.weight
                        if new_dist < distances[neighbor]:
                            distances[neighbor] = new_dist
        
        # 检查可达性
        reachable_nodes = sum(1 for d in distances if d != float('inf'))
        all_reachable = reachable_nodes == vertex_num
        
        return distances, all_reachable
    
    def validate_graph_properties(self, edge_map: Dict[int, List[Edge]], 
                                 vertex_num: int) -> Dict[str, Any]:
        """
        验证图的基本性质
        
        Args:
            edge_map: 边映射
            vertex_num: 顶点数量
            
        Returns:
            验证结果字典
        """
        results = {}
        
        # 1. 连通性验证
        if vertex_num > 0:
            bfs_tree, is_connected = self.run_bfs_validation(vertex_num, edge_map, 0)
            results['connectivity'] = {
                'is_connected': is_connected,
                'connected_components': 1 if is_connected else self._count_connected_components(edge_map, vertex_num),
                'bfs_tree_size': len(bfs_tree)
            }
        else:
            results['connectivity'] = {'is_connected': True, 'connected_components': 0, 'bfs_tree_size': 0}
        
        # 2. 路径分析
        if vertex_num > 0:
            distances, all_reachable = self.run_sssp_validation(vertex_num, edge_map, 0)
            finite_distances = [d for d in distances if d != float('inf')]
            
            results['path_analysis'] = {
                'all_reachable': all_reachable,
                'max_distance': max(finite_distances) if finite_distances else 0.0,
                'avg_distance': sum(finite_distances) / len(finite_distances) if finite_distances else 0.0,
                'diameter': max(finite_distances) if finite_distances else 0.0
            }
        else:
            results['path_analysis'] = {'all_reachable': True, 'max_distance': 0.0, 'avg_distance': 0.0, 'diameter': 0.0}
        
        # 3. 度分布分析
        degrees = [len(edge_map.get(i, [])) for i in range(vertex_num)]
        results['degree_analysis'] = {
            'total_edges': sum(degrees),
            'avg_degree': sum(degrees) / vertex_num if vertex_num > 0 else 0.0,
            'max_degree': max(degrees) if degrees else 0,
            'min_degree': min(degrees) if degrees else 0,
            'degree_variance': self._calculate_variance(degrees)
        }
        
        return results
    
    def _count_connected_components(self, edge_map: Dict[int, List[Edge]], vertex_num: int) -> int:
        """计算连通分量数量"""
        visited = [False] * vertex_num
        components = 0
        
        for i in range(vertex_num):
            if not visited[i]:
                components += 1
                self._dfs_mark_component(edge_map, i, visited, vertex_num)
        
        return components
    
    def _dfs_mark_component(self, edge_map: Dict[int, List[Edge]], node: int, 
                           visited: List[bool], vertex_num: int):
        """DFS标记连通分量"""
        visited[node] = True
        
        if node in edge_map:
            for edge in edge_map[node]:
                neighbor = edge.dst_v
                if neighbor < vertex_num and not visited[neighbor]:
                    self._dfs_mark_component(edge_map, neighbor, visited, vertex_num)
    
    def _calculate_variance(self, values: List[float]) -> float:
        """计算方差"""
        if not values:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance
    
    def analyze_mesh_topology(self, edge_map: Dict[int, List[Edge]], mesh_size: int) -> Dict[str, Any]:
        """
        分析mesh拓扑特性
        
        Args:
            edge_map: 边映射
            mesh_size: mesh大小
            
        Returns:
            mesh分析结果
        """
        vertex_num = mesh_size * mesh_size
        results = {}
        
        # 1. 验证mesh规律性
        results['regularity'] = self._verify_mesh_regularity(edge_map, mesh_size)
        
        # 2. 计算mesh直径
        results['mesh_diameter'] = 2 * (mesh_size - 1)  # mesh的理论直径
        
        # 3. 验证对称性
        results['symmetry'] = self._verify_mesh_symmetry(edge_map, mesh_size)
        
        # 4. 基本图性质
        basic_properties = self.validate_graph_properties(edge_map, vertex_num)
        results.update(basic_properties)
        
        return results
    
    def _verify_mesh_regularity(self, edge_map: Dict[int, List[Edge]], mesh_size: int) -> Dict[str, Any]:
        """验证mesh网络规律性"""
        vertex_num = mesh_size * mesh_size
        regularity_errors = []
        
        for node_id in range(vertex_num):
            x, y = node_id % mesh_size, node_id // mesh_size
            expected_neighbors = []
            
            # 计算期望邻居
            if x > 0: expected_neighbors.append(y * mesh_size + (x - 1))  # West
            if x < mesh_size - 1: expected_neighbors.append(y * mesh_size + (x + 1))  # East
            if y > 0: expected_neighbors.append((y - 1) * mesh_size + x)  # North
            if y < mesh_size - 1: expected_neighbors.append((y + 1) * mesh_size + x)  # South
            
            # 获取实际邻居
            actual_neighbors = [edge.dst_v for edge in edge_map.get(node_id, [])]
            
            # 检查一致性
            for expected in expected_neighbors:
                if expected not in actual_neighbors:
                    regularity_errors.append(f"节点{node_id}缺少到节点{expected}的连接")
            
            for actual in actual_neighbors:
                if actual not in expected_neighbors:
                    regularity_errors.append(f"节点{node_id}有意外连接到节点{actual}")
        
        return {
            'is_regular': len(regularity_errors) == 0,
            'errors': regularity_errors
        }
    
    def _verify_mesh_symmetry(self, edge_map: Dict[int, List[Edge]], mesh_size: int) -> Dict[str, Any]:
        """验证mesh网络对称性"""
        symmetry_errors = []
        
        for node_id, edges in edge_map.items():
            for edge in edges:
                neighbor = edge.dst_v
                
                # 检查反向连接是否存在
                reverse_found = False
                if neighbor in edge_map:
                    for reverse_edge in edge_map[neighbor]:
                        if reverse_edge.dst_v == node_id:
                            reverse_found = True
                            break
                
                if not reverse_found:
                    symmetry_errors.append(f"连接{node_id}->{neighbor}缺少反向连接")
        
        return {
            'is_symmetric': len(symmetry_errors) == 0,
            'errors': symmetry_errors
        }


# 便捷函数
def validate_snnDL_topology_with_graphlib(topology_edges: Dict[int, List[Edge]], 
                                        topology_type: str = 'general',
                                        mesh_size: Optional[int] = None) -> Dict[str, Any]:
    """
    使用GraphLib算法验证SnnDL拓扑
    
    Args:
        topology_edges: 拓扑边字典
        topology_type: 拓扑类型 ('general', 'mesh')
        mesh_size: mesh大小（如果是mesh拓扑）
        
    Returns:
        验证结果字典
    """
    converter = GraphLibConverter()
    vertex_num = len(topology_edges) if topology_edges else 0
    
    if topology_type == 'mesh' and mesh_size:
        return converter.analyze_mesh_topology(topology_edges, mesh_size)
    else:
        return converter.validate_graph_properties(topology_edges, vertex_num)


if __name__ == "__main__":
    # 测试GraphLib转换器
    print("🔍 测试GraphLib转换器...")
    
    # 创建简单测试图
    test_edges = {
        0: [Edge(1, 1.0), Edge(2, 1.0)],
        1: [Edge(0, 1.0), Edge(3, 1.0)],
        2: [Edge(0, 1.0), Edge(3, 1.0)],
        3: [Edge(1, 1.0), Edge(2, 1.0)]
    }
    
    converter = GraphLibConverter()
    
    # 测试基本图验证
    results = converter.validate_graph_properties(test_edges, 4)
    
    print(f"📊 基本图验证结果:")
    print(f"  连通性: {results['connectivity']['is_connected']}")
    print(f"  平均度数: {results['degree_analysis']['avg_degree']:.2f}")
    print(f"  最大距离: {results['path_analysis']['max_distance']:.2f}")
    
    # 测试mesh验证
    print(f"\n🌐 测试2x2 mesh验证...")
    mesh_results = validate_snnDL_topology_with_graphlib(test_edges, 'mesh', 2)
    print(f"  规律性: {mesh_results['regularity']['is_regular']}")
    print(f"  对称性: {mesh_results['symmetry']['is_symmetric']}")
    
    print("✅ GraphLib转换器测试完成")