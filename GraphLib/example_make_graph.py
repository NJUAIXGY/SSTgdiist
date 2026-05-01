#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Yukun Feng
# @Date: 2025-01-06

import random
import sys
from pathlib import Path
from time import time

import click
import numpy as np
import yaml
from loguru import logger

from Common import BAND_Gbit_2_bit, Debug, Direction, Message
from GraphLib import KroneckerGraph, RandomGraph
from GraphNoc import GraphNoc

np.random.seed(0)
random.seed(0)


class GraphSimulator:
    def __init__(self, noc: GraphNoc, vertex_num, edge_csr) -> None:
        self.vertex_num = vertex_num
        self.edge_csr = edge_csr

        # mapping
        self.noc = noc
        self.noc.graph_mapping(self.vertex_num, self.edge_csr)

        self.debug = Debug(self.noc.x_chipnum, self.noc.y_chipnum)

    def bfs(self, root):
        t1 = time()

        # update root
        src_chip = self.noc.vertex_to_chip[root]
        self.noc.chip_matrix[src_chip].bfs_record[root] = (0, root)
        self.noc.chip_matrix[src_chip].router_broadcast(Message(root, 0))

        # router load
        current_msg_num = 0
        time_count = 0
        for chip in self.noc.chip_matrix:
            router_load = []
            for direct in Direction.five_direction:
                router_load.append(len(chip.msg_router_recv[direct]))
            router_load.append(len(chip.msg_pe_recv))
            self.debug.add_route_load(time_count, chip.id, router_load)

        # msg count
        for chip in self.noc.chip_matrix:
            chip.router_recevie()
            current_msg_num += len(chip.msg_parse_queue)

        # simulate
        msg_count = current_msg_num
        edge_count = 0

        while current_msg_num > 0:
            print(current_msg_num)
            time_count += 1
            current_msg_num = 0

            # router parse and pe process
            for chip in self.noc.chip_matrix:
                chip.router_parse()
                edge_count += chip.pe_process(chip.bfs_update)

            # router load
            for chip in self.noc.chip_matrix:
                router_load = []
                for direct in Direction.five_direction:
                    router_load.append(len(chip.msg_router_recv[direct]))
                router_load.append(len(chip.msg_pe_recv))
                self.debug.add_route_load(time_count, chip.id, router_load)

            # msg count
            for chip in self.noc.chip_matrix:
                chip.router_recevie()
                current_msg_num += len(chip.msg_parse_queue)
            msg_count += current_msg_num

        t2 = time()

        # Gather results
        bfs_tree = {}
        for chip in self.noc.chip_matrix:
            bfs_tree.update(chip.bfs_record)
        print(time_count)
        finish_time = time_count * self.noc.router_router_delay
        GTEPS = edge_count / finish_time / BAND_Gbit_2_bit

        # BFS Report
        print(f'\n')
        logger.info(f'===================BFS Final Report===================')
        logger.info(
            f'NOC Total Chips Num: {self.noc.x_chipnum} * {self.noc.y_chipnum}')
        logger.info(
            f'NOC RouterRouterBandWid(Gbps): {self.noc.config["RouterRouterBandWid(Gbps)"]}')
        logger.info(f'NOC Vertex Num Per Chip: {self.noc.vertex_num_per_chip}')
        logger.info(f'BFS Message Processing Num: {msg_count}')
        logger.info(f'BFS Visit Edge Num = {edge_count}')
        logger.info(f'BFS Running Time(s): {finish_time}')
        logger.info(f'BFS GTEPS = {GTEPS}\n')
        logger.info(f'BFS simulation finished! TIME COST = {t2-t1:.2f}s')

        return bfs_tree

    def bfs_validate(self, root, bfs_tree):
        # bfs algo
        queue = [root]
        std_tree = []
        check = [False] * self.vertex_num
        check[root] = True
        while len(queue) > 0:
            a = []
            for _ in range(len(queue)):
                src_v = queue.pop(0)
                check[src_v] = True
                a.append(src_v)
                for edge in self.edge_csr[src_v]:
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

    def evaluate(self):
        # dynamic load analysis
        self.debug.route_load_analysis()

        # static mapping evaluation


def make_graph(scale, edgefactor, mode='random'):
    logger.info(
        f'Graph built start: <V, E> = <{2 ** scale}, {2 ** scale * edgefactor}>')
    t1 = time()

    if mode == 'random':
        num_v = 2 ** scale
        num_e = num_v * edgefactor
        rg = RandomGraph(num_v, num_e)
        rg.add_random_edges(num_e)
        vertex_num = rg.vertex_num
        edge_map = rg.edge_map
    elif mode == 'kronecker':
        probArr = [1, 0.3, 0.3, 0.2]
        kg = KroneckerGraph(scale, edgefactor, probArr)
        kg.make_graph()
        edge_map = kg.edge_table()
        vertex_num = kg.vertex_num

    t2 = time()
    logger.info(f'Graph generated successful! TIME COST = {t2-t1:.2f}s')

    return vertex_num, edge_map


@ click.command()
@ click.argument('npu-dir', type=Path, default='./config/npu_config_new.yaml')
@ click.argument('scale', type=int, default=13)
@ click.option('-e', '--edgefactor', default=16, type=int)
def process(npu_dir, scale, edgefactor):
    with open(npu_dir, 'r', encoding='utf-8') as stream:
        npu_config = yaml.safe_load(stream)

    # set logger
    logger.remove()
    handler_id = logger.add(sys.stderr, level="DEBUG")

    # make graph
    vertex_num, edge_csr = make_graph(scale, edgefactor, mode='random')

    # build simulation
    noc = GraphNoc(npu_config)
    simulator = GraphSimulator(noc, vertex_num, edge_csr)
    bfs_tree = simulator.bfs(0)

    # validate
    simulator.bfs_validate(0, bfs_tree)

    # evaluate
    simulator.evaluate()


if __name__ == "__main__":
    process()
