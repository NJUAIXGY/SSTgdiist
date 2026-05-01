#!/usr/bin/env python3
"""
SnnDL脉冲数据解析器

解析SnnDL脉冲数据文件，提取脉冲时序信息
"""

import os
from typing import Dict, List, Tuple


class SpikeDataParser:
    """SnnDL脉冲数据解析器"""
    
    def __init__(self):
        """初始化解析器"""
        pass
    
    def parse_spike_file(self, spike_file: str) -> List[Tuple[int, int]]:
        """
        解析脉冲数据文件
        
        Args:
            spike_file: 脉冲数据文件路径
            
        Returns:
            脉冲事件列表 [(neuron_id, timestamp), ...]
        """
        if not os.path.exists(spike_file):
            raise FileNotFoundError(f"脉冲文件不存在: {spike_file}")
        
        spikes = []
        
        try:
            with open(spike_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            neuron_id = int(parts[0])
                            timestamp = int(parts[1])
                            spikes.append((neuron_id, timestamp))
        except Exception as e:
            print(f"解析脉冲文件失败 {spike_file}: {e}")
            
        return spikes