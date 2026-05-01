#!/usr/bin/env python3
"""
SnnDL性能分析器

提供网络性能瓶颈分析、异常检测和验证报告生成功能
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

from .converter import Edge


class PerformanceAnalyzer:
    """
    SnnDL网络性能分析器
    
    分析网络性能瓶颈、检测异常模式、生成综合验证报告
    """
    
    def __init__(self):
        """初始化分析器"""
        pass
    
    def detect_network_anomalies(self, graphs: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """
        检测网络异常
        
        Args:
            graphs: 包含各层拓扑的字典
            
        Returns:
            异常列表
        """
        print("🔍 检测网络异常...")
        
        anomalies = []
        
        # 1. 检测孤立节点
        anomalies.extend(self._detect_isolated_nodes(graphs))
        
        # 2. 检测连接异常
        anomalies.extend(self._detect_connection_anomalies(graphs))
        
        # 3. 检测权重异常
        anomalies.extend(self._detect_weight_anomalies(graphs.get('data_graph', {})))
        
        # 4. 检测拓扑不一致
        anomalies.extend(self._detect_topology_inconsistencies(graphs))
        
        print(f"  📊 检测到{len(anomalies)}个异常")
        return anomalies
    
    def analyze_performance_bottlenecks(self, physical_topology: Dict[int, List[Edge]], 
                                       data_topology: Dict[int, List[Edge]]) -> Dict[str, Any]:
        """
        分析网络性能瓶颈
        
        Args:
            physical_topology: 物理层拓扑
            data_topology: 数据层拓扑
            
        Returns:
            性能分析结果
        """
        print("🔍 分析网络性能瓶颈...")
        
        analysis = {
            'bottlenecks': [],
            'hotspots': [],
            'load_analysis': {},
            'communication_efficiency': {}
        }
        
        # 1. 通信热点分析
        hotspots = self._analyze_communication_hotspots(data_topology)
        analysis['hotspots'] = hotspots
        
        # 2. 负载均衡分析
        load_analysis = self._analyze_load_balance(data_topology)
        analysis['load_analysis'] = load_analysis
        
        # 3. 通信效率分析
        comm_efficiency = self._analyze_communication_efficiency(
            physical_topology, data_topology)
        analysis['communication_efficiency'] = comm_efficiency
        
        # 4. 瓶颈节点识别
        bottlenecks = self._identify_bottleneck_nodes(
            hotspots, load_analysis, comm_efficiency)
        analysis['bottlenecks'] = bottlenecks
        
        print(f"  📊 识别出{len(bottlenecks)}个性能瓶颈")
        return analysis
    
    def generate_validation_report(self, validation_results: Dict[str, Any],
                                 anomalies: List[Dict[str, Any]],
                                 performance_analysis: Dict[str, Any]) -> str:
        """
        生成综合验证报告
        
        Args:
            validation_results: 验证结果
            anomalies: 异常列表
            performance_analysis: 性能分析结果
            
        Returns:
            报告文本
        """
        print("📝 生成验证报告...")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""
# SnnDL网络拓扑验证报告
生成时间: {timestamp}

## 📊 验证概览
"""
        
        # 验证概览
        total_tests = 0
        passed_tests = 0
        
        for layer_name, layer_result in validation_results.items():
            if isinstance(layer_result, dict) and 'valid' in layer_result:
                total_tests += 1
                if layer_result['valid']:
                    passed_tests += 1
        
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        overall_status = "✅ 通过" if pass_rate == 100 else "❌ 失败" if pass_rate < 50 else "⚠️ 部分通过"
        
        report += f"""
- 总体状态: {overall_status}
- 验证通过率: {pass_rate:.1f}% ({passed_tests}/{total_tests})
- 检测异常: {len(anomalies)}个
- 性能瓶颈: {len(performance_analysis.get('bottlenecks', []))}个

"""
        
        # 详细验证结果
        report += "## 🔍 详细验证结果\n\n"
        
        for layer_name, layer_result in validation_results.items():
            if not isinstance(layer_result, dict):
                continue
                
            status = "✅" if layer_result.get('valid', False) else "❌"
            report += f"### {layer_name.upper()}层验证 {status}\n\n"
            
            if layer_name == 'physical':
                report += self._format_physical_results(layer_result)
            elif layer_name == 'logical':
                report += self._format_logical_results(layer_result)
            elif layer_name == 'data':
                report += self._format_data_results(layer_result)
            elif layer_name == 'consistency':
                report += self._format_consistency_results(layer_result)
            
            report += "\n"
        
        # 异常检测结果
        if anomalies:
            report += "## 🚨 异常检测结果\n\n"
            
            anomaly_types = {}
            for anomaly in anomalies:
                anomaly_type = anomaly.get('type', 'unknown')
                if anomaly_type not in anomaly_types:
                    anomaly_types[anomaly_type] = []
                anomaly_types[anomaly_type].append(anomaly)
            
            for anomaly_type, anomaly_list in anomaly_types.items():
                report += f"### {anomaly_type}\n"
                for anomaly in anomaly_list[:5]:  # 最多显示5个
                    report += f"- {anomaly.get('description', str(anomaly))}\n"
                if len(anomaly_list) > 5:
                    report += f"- ... 还有{len(anomaly_list) - 5}个类似异常\n"
                report += "\n"
        
        # 性能分析结果
        if performance_analysis.get('bottlenecks') or performance_analysis.get('hotspots'):
            report += "## ⚡ 性能分析结果\n\n"
            
            if performance_analysis.get('hotspots'):
                report += "### 通信热点\n"
                for hotspot in performance_analysis['hotspots'][:5]:
                    report += f"- PE{hotspot['node']}: {hotspot['connections']}个连接, 权重总和{hotspot['total_weight']:.2f}\n"
                report += "\n"
            
            if performance_analysis.get('bottlenecks'):
                report += "### 性能瓶颈\n"
                for bottleneck in performance_analysis['bottlenecks'][:5]:
                    report += f"- {bottleneck['description']}\n"
                report += "\n"
        
        # 建议和总结
        report += "## 💡 建议和总结\n\n"
        report += self._generate_recommendations(validation_results, anomalies, performance_analysis)
        
        print("  📄 验证报告生成完成")
        return report
    
    def _detect_isolated_nodes(self, graphs: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """检测孤立节点"""
        anomalies = []
        
        for graph_name, graph_data in graphs.items():
            if isinstance(graph_data, dict) and 'edges' in graph_data:
                edges = graph_data['edges']
                nodes = graph_data.get('nodes', [])
                
                # 找到没有边的节点
                isolated_nodes = []
                for node in nodes:
                    if node not in edges or not edges[node]:
                        isolated_nodes.append(node)
                
                if isolated_nodes:
                    anomalies.append({
                        'type': 'isolated_nodes',
                        'layer': graph_name,
                        'nodes': isolated_nodes,
                        'description': f"{graph_name}层存在{len(isolated_nodes)}个孤立节点: {isolated_nodes}"
                    })
        
        return anomalies
    
    def _detect_connection_anomalies(self, graphs: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """检测连接异常"""
        anomalies = []
        
        # 检测度数异常
        for graph_name, graph_data in graphs.items():
            if isinstance(graph_data, dict) and 'edges' in graph_data:
                edges = graph_data['edges']
                
                degrees = [len(edge_list) for edge_list in edges.values()]
                if not degrees:
                    continue
                
                avg_degree = sum(degrees) / len(degrees)
                max_degree = max(degrees)
                min_degree = min(degrees)
                
                # 检测度数异常大的节点
                for node, edge_list in edges.items():
                    degree = len(edge_list)
                    if degree > 2 * avg_degree and degree > 10:
                        anomalies.append({
                            'type': 'high_degree_node',
                            'layer': graph_name,
                            'node': node,
                            'degree': degree,
                            'avg_degree': avg_degree,
                            'description': f"{graph_name}层节点{node}度数异常高({degree}), 平均度数({avg_degree:.1f})"
                        })
        
        return anomalies
    
    def _detect_weight_anomalies(self, data_edges: Dict[int, List[Edge]]) -> List[Dict[str, Any]]:
        """检测权重异常"""
        anomalies = []
        
        if not data_edges:
            return anomalies
        
        all_weights = []
        for edge_list in data_edges.values():
            for edge in edge_list:
                all_weights.append(edge.weight)
        
        if not all_weights:
            return anomalies
        
        avg_weight = sum(all_weights) / len(all_weights)
        max_weight = max(all_weights)
        min_weight = min(all_weights)
        
        # 检测异常权重
        for node, edge_list in data_edges.items():
            for edge in edge_list:
                if edge.weight > 5 * avg_weight and edge.weight > 100:
                    anomalies.append({
                        'type': 'excessive_weight',
                        'source': edge.dst_v,
                        'target': node,
                        'weight': edge.weight,
                        'avg_weight': avg_weight,
                        'description': f"PE{edge.dst_v}->PE{node}权重异常大({edge.weight:.2f}), 平均权重({avg_weight:.2f})"
                    })
                elif edge.weight < 0:
                    anomalies.append({
                        'type': 'negative_weight', 
                        'source': edge.dst_v,
                        'target': node,
                        'weight': edge.weight,
                        'description': f"PE{edge.dst_v}->PE{node}存在负权重({edge.weight:.2f})"
                    })
        
        return anomalies
    
    def _detect_topology_inconsistencies(self, graphs: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """检测拓扑不一致"""
        anomalies = []
        
        # 检查节点数量一致性
        node_counts = {}
        for graph_name, graph_data in graphs.items():
            if isinstance(graph_data, dict) and 'nodes' in graph_data:
                node_counts[graph_name] = len(graph_data['nodes'])
        
        if len(set(node_counts.values())) > 1:
            anomalies.append({
                'type': 'node_count_inconsistency',
                'node_counts': node_counts,
                'description': f"各层节点数量不一致: {node_counts}"
            })
        
        return anomalies
    
    def _analyze_communication_hotspots(self, data_edges: Dict[int, List[Edge]]) -> List[Dict[str, Any]]:
        """分析通信热点"""
        hotspots = []
        
        # 计算每个节点的通信负载
        node_loads = {}
        
        for target_node, edge_list in data_edges.items():
            total_weight = sum(edge.weight for edge in edge_list)
            node_loads[target_node] = {
                'connections': len(edge_list),
                'total_weight': total_weight,
                'avg_weight': total_weight / len(edge_list) if edge_list else 0.0
            }
        
        # 识别热点（连接数或权重总和超过平均值的2倍）
        if node_loads:
            avg_connections = sum(load['connections'] for load in node_loads.values()) / len(node_loads)
            avg_total_weight = sum(load['total_weight'] for load in node_loads.values()) / len(node_loads)
            
            for node, load in node_loads.items():
                if (load['connections'] > 2 * avg_connections or 
                    load['total_weight'] > 2 * avg_total_weight):
                    hotspots.append({
                        'node': node,
                        'connections': load['connections'],
                        'total_weight': load['total_weight'],
                        'avg_weight': load['avg_weight'],
                        'hotspot_score': (load['connections'] / avg_connections + 
                                        load['total_weight'] / avg_total_weight) / 2
                    })
        
        # 按热点分数排序
        hotspots.sort(key=lambda x: x['hotspot_score'], reverse=True)
        
        return hotspots
    
    def _analyze_load_balance(self, data_edges: Dict[int, List[Edge]]) -> Dict[str, Any]:
        """分析负载均衡"""
        if not data_edges:
            return {'balanced': True, 'variance': 0.0}
        
        # 计算每个节点的负载
        loads = [len(edge_list) for edge_list in data_edges.values()]
        
        avg_load = sum(loads) / len(loads)
        variance = sum((load - avg_load) ** 2 for load in loads) / len(loads)
        std_dev = variance ** 0.5
        
        # 负载均衡度判断
        is_balanced = std_dev < avg_load * 0.5  # 标准差小于平均值的50%
        
        return {
            'balanced': is_balanced,
            'avg_load': avg_load,
            'variance': variance,
            'std_dev': std_dev,
            'max_load': max(loads),
            'min_load': min(loads)
        }
    
    def _analyze_communication_efficiency(self, physical_edges: Dict[int, List[Edge]],
                                        data_edges: Dict[int, List[Edge]]) -> Dict[str, Any]:
        """分析通信效率"""
        efficiency_scores = []
        long_distance_connections = []
        
        mesh_size = int(len(physical_edges) ** 0.5)  # 假设是方形mesh
        
        for target_node, edge_list in data_edges.items():
            for edge in edge_list:
                source_node = edge.dst_v
                
                # 计算物理距离
                distance = self._calculate_mesh_distance(source_node, target_node, mesh_size)
                weight = edge.weight
                
                # 效率分数 = 权重 / 距离 (权重大、距离小的连接效率高)
                efficiency = weight / max(distance, 1)
                efficiency_scores.append(efficiency)
                
                # 记录长距离连接
                if distance > mesh_size // 2:
                    long_distance_connections.append({
                        'source': source_node,
                        'target': target_node,
                        'distance': distance,
                        'weight': weight,
                        'efficiency': efficiency
                    })
        
        avg_efficiency = sum(efficiency_scores) / len(efficiency_scores) if efficiency_scores else 0.0
        
        return {
            'avg_efficiency': avg_efficiency,
            'long_distance_connections': len(long_distance_connections),
            'efficiency_scores': efficiency_scores,
            'inefficient_connections': [conn for conn in long_distance_connections if conn['efficiency'] < avg_efficiency]
        }
    
    def _identify_bottleneck_nodes(self, hotspots: List[Dict], 
                                  load_analysis: Dict, 
                                  comm_efficiency: Dict) -> List[Dict[str, Any]]:
        """识别瓶颈节点"""
        bottlenecks = []
        
        # 基于热点识别瓶颈
        for hotspot in hotspots[:3]:  # 前3个热点
            if hotspot['hotspot_score'] > 2.0:  # 热点分数超过2.0
                bottlenecks.append({
                    'type': 'communication_hotspot',
                    'node': hotspot['node'],
                    'score': hotspot['hotspot_score'],
                    'description': f"PE{hotspot['node']}是通信热点，连接数{hotspot['connections']}，权重总和{hotspot['total_weight']:.2f}"
                })
        
        # 基于负载不均衡识别瓶颈
        if not load_analysis.get('balanced', True):
            bottlenecks.append({
                'type': 'load_imbalance',
                'variance': load_analysis['variance'],
                'description': f"网络负载不均衡，方差{load_analysis['variance']:.2f}"
            })
        
        # 基于通信效率识别瓶颈
        inefficient_connections = comm_efficiency.get('inefficient_connections', [])
        if len(inefficient_connections) > 5:  # 超过5个低效连接
            bottlenecks.append({
                'type': 'communication_inefficiency',
                'count': len(inefficient_connections),
                'description': f"存在{len(inefficient_connections)}个低效长距离连接"
            })
        
        return bottlenecks
    
    def _calculate_mesh_distance(self, node1: int, node2: int, mesh_size: int) -> int:
        """计算mesh距离"""
        x1, y1 = node1 % mesh_size, node1 // mesh_size
        x2, y2 = node2 % mesh_size, node2 // mesh_size
        return abs(x1 - x2) + abs(y1 - y2)
    
    def _format_physical_results(self, results: Dict) -> str:
        """格式化物理层结果"""
        text = f"- 连通性: {'✅ 通过' if results.get('connectivity') else '❌ 失败'}\n"
        text += f"- 规律性: {'✅ 通过' if results.get('regularity') else '❌ 失败'}\n"
        text += f"- 对称性: {'✅ 通过' if results.get('symmetry') else '❌ 失败'}\n"
        text += f"- 网络直径: {results.get('diameter', 'N/A')}\n"
        text += f"- 平均度数: {results.get('average_degree', 0):.2f}\n"
        text += f"- 总边数: {results.get('total_edges', 0)}\n"
        
        if results.get('errors'):
            text += f"- 错误: {len(results['errors'])}个\n"
            
        return text
    
    def _format_logical_results(self, results: Dict) -> str:
        """格式化逻辑层结果"""
        text = f"- 层结构: {'✅ 有效' if results.get('layer_structure_valid') else '❌ 无效'}\n"
        text += f"- 前馈连接: {'✅ 有效' if results.get('feedforward_valid') else '❌ 无效'}\n"
        text += f"- 连通性: {'✅ 通过' if results.get('connectivity') else '❌ 失败'}\n"
        text += f"- 逻辑连接数: {results.get('total_logical_connections', 0)}\n"
        
        if results.get('anomalies'):
            text += f"- 异常数: {len(results['anomalies'])}\n"
            
        return text
    
    def _format_data_results(self, results: Dict) -> str:
        """格式化数据层结果"""
        text = f"- 连接模式: {'✅ 有效' if results.get('pattern_valid') else '❌ 无效'}\n"
        text += f"- 权重分布: {'✅ 正常' if results.get('weight_distribution_valid') else '❌ 异常'}\n"
        text += f"- 连通性: {'✅ 通过' if results.get('connectivity') else '❌ 失败'}\n"
        text += f"- 数据连接数: {results.get('total_data_connections', 0)}\n"
        text += f"- 前馈连接: {results.get('feedforward_connections', 0)}\n"
        text += f"- 反向连接: {results.get('backward_connections', 0)}\n"
        text += f"- 平均权重强度: {results.get('avg_connection_strength', 0):.4f}\n"
        
        return text
    
    def _format_consistency_results(self, results: Dict) -> str:
        """格式化一致性结果"""
        text = f"- 节点映射: {'✅ 一致' if results.get('node_mapping_consistent') else '❌ 不一致'}\n"
        text += f"- 逻辑数据一致性: {'✅ 一致' if results.get('logical_data_consistent') else '❌ 不一致'}\n"
        text += f"- 路由效率: {'✅ 高效' if results.get('routing_efficient') else '⚠️ 可优化'}\n"
        
        return text
    
    def _generate_recommendations(self, validation_results: Dict[str, Any],
                                anomalies: List[Dict[str, Any]],
                                performance_analysis: Dict[str, Any]) -> str:
        """生成建议"""
        recommendations = []
        
        # 基于验证结果生成建议
        for layer_name, layer_result in validation_results.items():
            if isinstance(layer_result, dict) and not layer_result.get('valid', True):
                if layer_name == 'physical':
                    recommendations.append("建议检查mesh路由器配置和连接")
                elif layer_name == 'logical':
                    recommendations.append("建议检查神经网络层定义和前馈连接配置")
                elif layer_name == 'data':
                    recommendations.append("建议检查权重文件和连接模式")
        
        # 基于异常生成建议
        anomaly_types = set(anomaly.get('type', '') for anomaly in anomalies)
        if 'excessive_weight' in anomaly_types:
            recommendations.append("建议检查和调整异常大的权重值")
        if 'isolated_nodes' in anomaly_types:
            recommendations.append("建议检查孤立节点的连接配置")
        
        # 基于性能分析生成建议
        if performance_analysis.get('bottlenecks'):
            recommendations.append("建议优化通信热点和负载均衡")
        
        if not recommendations:
            recommendations.append("网络配置良好，可以进行性能优化和扩展测试")
        
        return "\n".join(f"- {rec}" for rec in recommendations)


if __name__ == "__main__":
    # 测试性能分析器
    print("🔍 测试性能分析器...")
    
    analyzer = PerformanceAnalyzer()
    print("✅ 性能分析器初始化完成")