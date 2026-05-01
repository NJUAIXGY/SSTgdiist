#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Yukun Feng
# @Date: 2024-12-11


import random
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

try:
    import matplotlib.pyplot as plt  # 可选依赖，仅用于可视化
except Exception:
    plt = None
try:
    import networkx as nx  # 可选依赖，仅用于KroneckerGraph/可视化
except Exception:
    nx = None
import numpy as np
try:
    from loguru import logger  # 可选依赖，用于日志
except Exception:
    class _FallbackLogger:
        def info(self, *args, **kwargs):
            print("[INFO]", *args)
        def critical(self, *args, **kwargs):
            print("[CRITICAL]", *args)
    logger = _FallbackLogger()

try:
    from .KroneckerGenerator import GenerateStochasticKron, InitMatrix  # 可选依赖
except Exception:
    GenerateStochasticKron = None
    class InitMatrix:  # 占位，避免导入失败影响其它功能
        def __init__(self, *args, **kwargs):
            pass
        def make(self, *args, **kwargs):
            pass
        def makeStochasticAB(self, *args, **kwargs):
            pass
        def makeStochasticCustom(self, *args, **kwargs):
            pass

MAX_INT = 9999999
Kronecker_BASIC_NODE = 2


@dataclass
class Edge:
    dst_v: np.int64
    weight: np.float32


class RandomGraph:
    def __init__(self, numv, nume) -> None:
        self.vertex_num = numv
        self.edge_num = nume
        self.edge_map = {}

    def _add_edge(self, v0, v1, weight):
        if v0 not in self.edge_map:
            self.edge_map[v0] = [Edge(v1, weight)]
        else:
            self.edge_map[v0].append(Edge(v1, weight))

    def add_random_edges(self, nume):
        for _ in range(nume):
            v0 = random.randint(0, self.vertex_num - 1)
            v1 = random.randint(0, self.vertex_num - 1)
            weight = random.random()
            self._add_edge(v0, v1, weight)
            self._add_edge(v1, v0, weight)


class KroneckerGraph():
    def __init__(self, scale, factor, prob_mat=None) -> None:
        self.initial = InitMatrix(Kronecker_BASIC_NODE)
        self.initial.make()
        if prob_mat == None:
            self.initial.makeStochasticAB(0.7, 0.3)
        else:
            self.initial.makeStochasticCustom(probArr=np.array(prob_mat))
        self.scale = scale
        self.vertex_num = Kronecker_BASIC_NODE ** scale
        self.edge_num = self.vertex_num * factor

    def make_graph(self):
        if nx is None:
            raise RuntimeError("networkx is required for KroneckerGraph")
        self.graph = GenerateStochasticKron(
            self.initial, self.scale, deleteSelfLoopsForStats=True, customEdges=True, edges=self.edge_num)

    def edge_table(self):
        if nx is None:
            raise RuntimeError("networkx is required for KroneckerGraph")
        self.edge_map = {}
        edges = nx.edges(self.graph)
        for v0, v1 in edges:
            weight = random.random()
            if v0 not in self.edge_map:
                self.edge_map[v0] = [Edge(v1, weight)]
            else:
                self.edge_map[v0].append(Edge(v1, weight))

            if v1 not in self.edge_map:
                self.edge_map[v1] = [Edge(v0, weight)]
            else:
                self.edge_map[v1].append(Edge(v0, weight))

        return self.edge_map

    def plot_network(self):
        if nx is None or plt is None:
            raise RuntimeError("matplotlib and networkx are required for plotting")
        edge_array = np.array(nx.adjacency_matrix(self.graph).todense())
        plt.imshow(edge_array)
        plt.show()

    def plot_graph(self):
        if nx is None or plt is None:
            raise RuntimeError("matplotlib and networkx are required for plotting")
        fig = plt.figure()
        nx.draw(self.graph, pos=nx.circular_layout(self.graph), node_color='green', edge_color='green',
                node_size=8, width=1, alpha=1)
        fig.set_facecolor('black')
        plt.show()


class GraphValidator():
    def bfs(vertex_num, edge_map, root, bfs_tree):
        # bfs algo
        queue = [root]
        std_tree = []
        check = [False] * vertex_num
        check[root] = True
        while len(queue) > 0:
            a = []
            for _ in range(len(queue)):
                src_v = queue.pop(0)
                check[src_v] = True
                a.append(src_v)
                for edge in edge_map[src_v]:
                    if check[src_v]:
                        continue
                    queue.append(edge.dst_v)
            std_tree.append(a)

        # validation
        validation = True
        for level, sets in enumerate(std_tree):
            for v in sets:
                if bfs_tree[v][0] != level:
                    validation = False
                    logger.critical(
                        f'BFS Validation: Vertex {v} level {bfs_tree[v][0]}, std level {level}')

        if validation:
            logger.info(f'BFS Validation: Successful!!!')
        else:
            logger.critical(f'BFS Validation: Failed!!!')

    def sssp(vertex_num, edge_map, root, sssp_tree):
        # sssp algo
        dist = [MAX_INT] * vertex_num
        dist[root] = 0
        book = [False] * vertex_num
        book[root] = 0
        queue = [root]
        while len(queue) > 0:
            src_v = queue.pop(0)
            for edge in edge_map[src_v]:
                if dist[src_v] + edge.weight < dist[edge.dst_v]:
                    dist[edge.dst_v] = dist[src_v] + edge.weight
                    if not book[edge.dst_v]:
                        queue.append(edge.dst_v)
                        book[src_v] = True
            book[src_v] = False

        # # NOTE: bellman-ford (too slow)
        # for _ in range(vertex_num):
        #     for src_v in edge_map.keys():
        #         for edge in edge_map[src_v]:
        #             if dist[edge.dst_v] > dist[src_v] + edge.weight:
        #                 dist[edge.dst_v] = dist[src_v] + edge.weight

        # validation
        validation = True
        for i in range(vertex_num):
            if dist[i] != sssp_tree[i][0]:
                validation = False
                logger.critical(
                    f'SSSP Validation: Vertex {i} min_dist {sssp_tree[i][0]}, std min_dist {dist[i]}')

        if validation:
            logger.info(f'SSSP Validation: Successful!!!')
        else:
            logger.critical(f'SSSP Validation: Failed!!!')


class SNNSpikeValidator:
    """基于图的SNN脉冲传输验证器

    功能：
    - 连通性/跳数估计（基于物理拓扑）
    - 事件级匹配（发放->接收），检查缺失/重复/越界提前或延迟

    说明：保持纯算法，不依赖SST，仅使用简单的邻接表与时间参数。
    """

    @staticmethod
    def _neighbors(edge_map: Dict[int, List[Edge]], node: int) -> List[int]:
        return [int(e.dst_v) for e in edge_map.get(node, [])]

    @staticmethod
    def shortest_hops(vertex_num: int, edge_map: Dict[int, List[Edge]], src: int, dst: int) -> Optional[int]:
        """基于无权BFS的最短跳数。返回 None 表示不可达。"""
        if src == dst:
            return 0
        if src < 0 or src >= vertex_num or dst < 0 or dst >= vertex_num:
            return None
        visited = [False] * vertex_num
        q: List[Tuple[int, int]] = [(src, 0)]
        visited[src] = True
        head = 0
        while head < len(q):
            node, d = q[head]
            head += 1
            for nb in SNNSpikeValidator._neighbors(edge_map, node):
                if nb == dst:
                    return d + 1
                if 0 <= nb < vertex_num and not visited[nb]:
                    visited[nb] = True
                    q.append((nb, d + 1))
        return None

    @staticmethod
    def build_expected_arrivals(
        physical_vertex_num: int,
        physical_edges: Dict[int, List[Edge]],
        neuron_to_node: Dict[int, int],
        synapse_map: Dict[int, List[int]],
        emitted_spikes: List[Tuple[int, float]],
        link_delay: float = 5.0,
        synaptic_delay: float = 0.0,
    ) -> Dict[int, List[float]]:
        """根据物理拓扑与神经元映射，生成每个后突触神经元的期望到达时间列表。

        参数：
        - physical_vertex_num/physical_edges: 物理网络（节点=PE，边=路由连边）
        - neuron_to_node: 神经元 -> 物理节点(PE)
        - synapse_map: 突触前神经元 -> 若干突触后神经元
        - emitted_spikes: 发放事件列表 [(pre_neuron, t_emit)]
        - link_delay: 每跳链路延迟（同单位）
        - synaptic_delay: 突触延迟（可按需要统一给定）
        返回：post_neuron -> [t_expected, ...]
        """
        expected: Dict[int, List[float]] = {}
        for pre, t_emit in emitted_spikes:
            if pre not in synapse_map:
                continue
            src_node = neuron_to_node.get(pre, None)
            if src_node is None:
                continue
            for post in synapse_map[pre]:
                dst_node = neuron_to_node.get(post, None)
                if dst_node is None:
                    continue
                hops = SNNSpikeValidator.shortest_hops(physical_vertex_num, physical_edges, src_node, dst_node)
                if hops is None:
                    # 不可达：用特殊标记（负时间）记录，后续将作为连通性失败/必然缺失
                    expected.setdefault(post, []).append(float('-inf'))
                    continue
                t_arrival = t_emit + hops * link_delay + synaptic_delay
                expected.setdefault(post, []).append(t_arrival)
        # 对每个post的期望到达时间排序，便于匹配
        for post in expected:
            expected[post].sort()
        return expected

    @staticmethod
    def validate_transmission(
        physical_vertex_num: int,
        physical_edges: Dict[int, List[Edge]],
        neuron_to_node: Dict[int, int],
        synapse_map: Dict[int, List[int]],
        emitted_spikes: List[Tuple[int, float]],
        received_spikes: List[Tuple[int, float]],
        link_delay: float = 5.0,
        synaptic_delay: float = 0.0,
        tolerance: float = 1.0,
    ) -> Dict:
        """事件级验证：将期望到达与观测接收进行匹配，统计缺失/重复/提前/延后。

        返回结构：
        {
          'summary': {...},
          'per_neuron': {
             post_id: {
               'expected': N, 'matched': M, 'missing': N-M,
               'extra': X, 'early': a, 'late': b,
               'near_miss': k, 'max_abs_delta': dmax
             }, ...
          }
        }
        """
        # 期望到达
        expected = SNNSpikeValidator.build_expected_arrivals(
            physical_vertex_num, physical_edges, neuron_to_node, synapse_map,
            emitted_spikes, link_delay, synaptic_delay)

        # 观测接收事件按神经元聚合、排序
        observed: Dict[int, List[float]] = {}
        for nid, t in received_spikes:
            observed.setdefault(nid, []).append(float(t))
        for nid in observed:
            observed[nid].sort()

        per_neuron: Dict[int, Dict] = {}
        total_expected = 0
        total_matched = 0
        total_missing = 0
        total_extra = 0
        total_early = 0
        total_late = 0
        total_near_miss = 0
        max_abs_delta = 0.0

        # 贪心匹配：对每个post的期望时间序列，与观测时间序列做双指针匹配
        for post, t_list in expected.items():
            obs = observed.get(post, [])
            i = 0  # expected idx
            j = 0  # observed idx
            matched = 0
            early = 0
            late = 0
            near_miss = 0
            local_max_abs_delta = 0.0

            # 非连通标记的期望视作必然缺失
            unavoidable_missing = sum(1 for t in t_list if t == float('-inf'))
            # 过滤出有效期望
            t_valid = [t for t in t_list if t != float('-inf')]

            while i < len(t_valid) and j < len(obs):
                te = t_valid[i]
                to = obs[j]
                delta = to - te
                abs_delta = abs(delta)
                local_max_abs_delta = max(local_max_abs_delta, abs_delta)
                max_abs_delta = max(max_abs_delta, abs_delta)

                if abs_delta <= tolerance:
                    matched += 1
                    i += 1
                    j += 1
                else:
                    # 没在容差内：向较早的一个推进
                    if to < te:
                        # 观测早于期望：这条观测可能是多余或属于下一个期望
                        early += 1
                        j += 1
                    else:
                        # 观测晚于期望：记录近失配，并推进期望
                        late += 1
                        i += 1
                    near_miss += 1

            missing = len(t_valid) - matched + unavoidable_missing
            extra = (len(obs) - j)  # 剩余未匹配观测

            per_neuron[post] = {
                'expected': len(t_list),
                'matched': matched,
                'missing': missing,
                'extra': extra,
                'early': early,
                'late': late,
                'near_miss': near_miss,
                'max_abs_delta': local_max_abs_delta,
            }

            total_expected += len(t_list)
            total_matched += matched
            total_missing += missing
            total_extra += extra
            total_early += early
            total_late += late
            total_near_miss += near_miss

        # 未出现在期望中的观测（完全无源post）：视为多余
        for post, obs in observed.items():
            if post not in per_neuron and post not in expected:
                per_neuron[post] = {
                    'expected': 0,
                    'matched': 0,
                    'missing': 0,
                    'extra': len(obs),
                    'early': 0,
                    'late': 0,
                    'near_miss': 0,
                    'max_abs_delta': 0.0,
                }
                total_extra += len(obs)

        summary = {
            'total_expected': total_expected,
            'total_matched': total_matched,
            'total_missing': total_missing,
            'total_extra': total_extra,
            'total_early': total_early,
            'total_late': total_late,
            'total_near_miss': total_near_miss,
            'max_abs_delta': max_abs_delta,
            'pass': (total_missing == 0 and total_extra == 0),
        }

        return {
            'summary': summary,
            'per_neuron': per_neuron,
        }

    @staticmethod
    def validate_conservation(
        synapse_map: Dict[int, List[int]],
        emitted_spikes: List[Tuple[int, float]],
        received_spikes: List[Tuple[int, float]],
    ) -> Dict:
        """计数守恒：预期接收总数 = sum(outdegree(pre) * emit_count(pre)) 与实际接收对比。"""
        outdeg = {pre: len(dst) for pre, dst in synapse_map.items()}
        emit_count: Dict[int, int] = {}
        for pre, _ in emitted_spikes:
            emit_count[pre] = emit_count.get(pre, 0) + 1
        expected_total = sum(outdeg.get(pre, 0) * cnt for pre, cnt in emit_count.items())

        recv_total = len(received_spikes)
        ok = (expected_total == recv_total)
        return {
            'expected_receives': expected_total,
            'observed_receives': recv_total,
            'delta': recv_total - expected_total,
            'pass': ok,
        }

    @staticmethod
    def validate_snn_spike_correctness(
        physical_vertex_num: int,
        physical_edges: Dict[int, List[Edge]],
        neuron_to_node: Dict[int, int],
        synapse_map: Dict[int, List[int]],
        emitted_spikes: List[Tuple[int, float]],
        received_spikes: List[Tuple[int, float]],
        link_delay: float = 5.0,
        synaptic_delay: float = 0.0,
        tolerance: float = 1.0,
    ) -> Dict:
        """综合验证：先做守恒检查，再做事件级匹配。"""
        cons = SNNSpikeValidator.validate_conservation(synapse_map, emitted_spikes, received_spikes)
        trans = SNNSpikeValidator.validate_transmission(
            physical_vertex_num, physical_edges, neuron_to_node, synapse_map,
            emitted_spikes, received_spikes, link_delay, synaptic_delay, tolerance,
        )
        return {
            'conservation': cons,
            'transmission': trans,
            'pass': cons['pass'] and trans['summary']['pass'],
        }
