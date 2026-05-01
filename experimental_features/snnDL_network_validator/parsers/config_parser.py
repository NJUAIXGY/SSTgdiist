#!/usr/bin/env python3
"""
SnnDL配置文件解析器

解析SnnDL Python配置文件，提取网络架构参数
"""

import os
import re
import ast
from typing import Dict, Any


class SnnDLConfigParser:
    """SnnDL配置文件解析器"""
    
    def __init__(self):
        """初始化解析器"""
        pass
    
    def parse_config_file(self, config_path: str) -> Dict[str, Any]:
        """
        解析SnnDL配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置参数字典
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        config = {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用正则表达式提取配置参数
            config.update(self._extract_basic_params(content))
            config.update(self._extract_layer_definitions(content))
            config.update(self._extract_network_params(content))
            
        except Exception as e:
            print(f"解析配置文件失败: {e}")
            
        return config
    
    def _extract_basic_params(self, content: str) -> Dict[str, Any]:
        """提取基础参数"""
        params = {}
        
        # 基础网络参数
        patterns = {
            'mesh_size': r'MESH_SIZE\s*=\s*(\d+)',
            'num_cores_per_pe': r'NUM_CORES_PER_PE\s*=\s*(\d+)', 
            'neurons_per_core': r'NEURONS_PER_CORE\s*=\s*(\d+)',
            'neurons_per_pe': r'NEURONS_PER_PE\s*=\s*(\d+)',
            'total_nodes': r'TOTAL_NODES\s*=\s*(\d+)',
            'simulation_time': r'SIMULATION_TIME\s*=\s*["\']([^"\']+)["\']'
        }
        
        for param_name, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                value = match.group(1)
                if param_name == 'simulation_time':
                    params[param_name] = value
                else:
                    params[param_name] = int(value)
        
        return params
    
    def _extract_layer_definitions(self, content: str) -> Dict[str, Any]:
        """提取层定义"""
        layer_definitions = {}
        
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
                    layer_definitions[layer_name] = layer_def
                except:
                    pass
        
        if layer_definitions:
            return {'layer_definitions': layer_definitions}
        else:
            return {}
    
    def _extract_network_params(self, content: str) -> Dict[str, Any]:
        """提取网络参数"""
        params = {}
        
        # 网络参数
        patterns = {
            'network_bandwidth': r'NETWORK_BANDWIDTH\s*=\s*["\']([^"\']+)["\']',
            'buffer_size': r'BUFFER_SIZE\s*=\s*["\']([^"\']+)["\']'
        }
        
        for param_name, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                params[param_name] = match.group(1)
        
        return params