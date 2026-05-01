#!/usr/bin/env python3
"""
SnnDL Network Topology Validator

基于GraphLib的SnnDL多核PE网络拓扑验证工具
支持物理层、逻辑层、数据层三层拓扑统一验证

Author: SnnDL Team
Version: 1.0.0
"""

from .core.topology_extractor import TopologyExtractor
from .core.validator import NetworkValidator 
from .core.converter import GraphLibConverter
from .core.analyzer import PerformanceAnalyzer

from .parsers.weight_parser import WeightFileParser
from .parsers.config_parser import SnnDLConfigParser

from .validators.physical_validator import PhysicalTopologyValidator
from .validators.logical_validator import LogicalTopologyValidator
from .validators.data_validator import DataTopologyValidator

__version__ = "1.0.0"
__author__ = "SnnDL Team"

class SnnDLNetworkTopologyValidator:
    """
    SnnDL网络拓扑验证器主类
    
    集成三层拓扑验证：
    - 物理层: 4x4 mesh路由器连接
    - 逻辑层: 分层神经网络连接  
    - 数据层: 权重矩阵连接模式
    """
    
    def __init__(self, config_file=None):
        """
        初始化验证器
        
        Args:
            config_file: SnnDL配置文件路径（可选）
        """
        self.config_file = config_file
        self.topology_extractor = TopologyExtractor()
        self.validator = NetworkValidator()
        self.converter = GraphLibConverter() 
        self.analyzer = PerformanceAnalyzer()
        
        # 拓扑数据存储
        self.physical_topology = {}
        self.logical_topology = {}
        self.data_topology = {}
        
        # 验证结果存储
        self.validation_results = {}
        
    def extract_topologies(self, snnDL_config_path=None):
        """
        提取所有层拓扑结构
        
        Args:
            snnDL_config_path: SnnDL配置文件路径
        """
        config_path = snnDL_config_path or self.config_file
        if not config_path:
            raise ValueError("需要提供SnnDL配置文件路径")
            
        # 提取三层拓扑
        self.physical_topology = self.topology_extractor.extract_physical_topology(config_path)
        self.logical_topology = self.topology_extractor.extract_logical_topology(config_path) 
        self.data_topology = self.topology_extractor.extract_data_topology(config_path)
        
        return {
            'physical': self.physical_topology,
            'logical': self.logical_topology, 
            'data': self.data_topology
        }
    
    def validate_all_layers(self):
        """
        执行全层拓扑验证
        
        Returns:
            验证结果字典
        """
        if not (self.physical_topology and self.logical_topology and self.data_topology):
            raise ValueError("请先调用extract_topologies()提取拓扑")
            
        self.validation_results = {
            'physical': self.validator.validate_physical_layer(self.physical_topology),
            'logical': self.validator.validate_logical_layer(self.logical_topology),
            'data': self.validator.validate_data_layer(self.data_topology),
            'consistency': self.validator.validate_cross_layer_consistency(
                self.physical_topology, self.logical_topology, self.data_topology)
        }
        
        return self.validation_results
    
    def detect_anomalies(self):
        """
        检测网络异常
        
        Returns:
            异常列表
        """
        return self.analyzer.detect_network_anomalies({
            'physical_graph': self.physical_topology,
            'logical_graph': self.logical_topology,
            'data_graph': self.data_topology
        })
    
    def analyze_performance(self):
        """
        分析网络性能瓶颈
        
        Returns:
            性能分析结果
        """
        return self.analyzer.analyze_performance_bottlenecks(
            self.physical_topology, self.data_topology)
    
    def generate_report(self, output_file=None):
        """
        生成验证报告
        
        Args:
            output_file: 输出文件路径（可选）
            
        Returns:
            报告内容字符串
        """
        if not self.validation_results:
            raise ValueError("请先运行validate_all_layers()")
            
        report = self.analyzer.generate_validation_report(
            self.validation_results, 
            self.detect_anomalies(),
            self.analyze_performance()
        )
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
                
        return report


# 便捷函数
def validate_snnDL_network(config_file, report_file=None):
    """
    便捷函数：一键验证SnnDL网络
    
    Args:
        config_file: SnnDL配置文件路径
        report_file: 报告输出文件路径（可选）
        
    Returns:
        验证结果和报告
    """
    validator = SnnDLNetworkTopologyValidator(config_file)
    
    # 提取拓扑
    topologies = validator.extract_topologies()
    
    # 执行验证
    results = validator.validate_all_layers()
    
    # 生成报告
    report = validator.generate_report(report_file)
    
    return {
        'topologies': topologies,
        'validation_results': results,
        'report': report
    }