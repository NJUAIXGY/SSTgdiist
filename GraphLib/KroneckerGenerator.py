import math
import random

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np


def convert(something):  # use networkx conversion from numpy array
    # g = nx.from_numpy_matrix(someNPMat)
    g = nx.to_networkx_graph(something)
    return g


# used to take away self loops in final graph for stat purposes
def deleteSelfLoops(graph, nNodes):
    nNodes = int(nNodes)
    for i in range(nNodes):
        for j in range(nNodes):
            if (i == j):
                graph[i, j] = 0
    return graph


class InitMatrix():

    def __init__(self, numNodes, W=None):
        self.numNodes = numNodes
        # initially we will take in the number of nodes when the object is created

    def getNumNodes(self):
        return self.numNodes

    def setNumNodes(self, v):
        self.numNodes = v

    def getValue(self, node1, node2):
        return self.W[node1, node2]

    def setValue(self, newVal, node1, node2):
        self.W[node1, node2] = newVal

    def getMtxSum(self):
        n = self.getNumNodes()
        s = 0.0
        for i in range(n):
            for j in range(n):
                s += self.getValue(i, j)
        int(s)
        return s

    def make(self):  # This makes a init matrix manual (user adds edges)
        n = self.numNodes  # getNumNodes(self)
        # Creates corret size of init matrix with all 0s
        initMat = np.zeros((n, n))
        self.W = initMat

    # takes np array of probs for each position in init matrix
    def makeStochasticCustom(self, probArr):
        n = self.numNodes
        length = n*n
        if (probArr.shape[0] != length):
            raise IOError(
                "Your array must be the length of postitions in your initMatrix")
        k = 0
        for i in range(n):
            for j in range(n):
                # for k in range(length):
                self.setValue(probArr[k], i, j)
                k = k + 1

    def makeStochasticAB(self, alpha, beta, selfloops=True):
        # parm check
        if (not (0.00 <= alpha <= 1.00)):
            raise IOError(
                "alpha (arguement 1) must be a value equal to or between 0 and 1; it is a probability")
        if (not (0.00 <= beta <= 1.00)):
            raise IOError(
                "beta (arguement 2) must be a value equal to or between 0 and 1; it is a probability")

        n = self.getNumNodes()

        # switch 1s and 0s for alpha and beta, keep self loops
        for i in range(n):
            for j in range(n):
                if (i == j):
                    if (selfloops == False):
                        self.setValue(alpha, i, j)
                elif (self.getValue(i, j) == 0):
                    self.setValue(beta, i, j)
                else:
                    self.setValue(alpha, i, j)

    # takes a nxgraph, alpha, and beta. Returns stochastic initMatrix.
    def makeStochasticABFromNetworkxGraph(self, nxgraph, alpha, beta):
        # return graph adj matrix as a np matrix
        adjMatrix = nx.to_numpy_matrix(nxgraph)

        n = adjMatrix.shape[0]  # get num nodes

        init = InitMatrix(n)
        init.make()
        for i in range(n):
            for j in range(n):
                init.setValue(adjMatrix[i, j], i, j)
        init.makeStochasticAB(alpha, beta)

        return init  # there is no gaurentee of self loops since these are other graph types generated as seeds

    # takes a nxgraph, Returns initMatrix.
    def makeFromNetworkxGraph(self, nxgraph):
        # return graph adj matrix as a np matrix
        adjMatrix = nx.to_numpy_matrix(nxgraph)

        n = adjMatrix.shape[0]  # get num nodes

        init = InitMatrix(n)
        init.make()
        for i in range(n):
            for j in range(n):
                init.setValue(adjMatrix[i, j], i, j)

        return init  # there is no gaurentee of self loops since these are other graph types generated as seeds

    def addEdge(self, node1, node2, edge=1):
        node1 = int(node1)
        node2 = int(node2)
        if edge == 0 or edge == float('inf'):
            raise ValueError("Cannot add a zero or infinite edge")

        self.W[node1, node2] = edge

    def addSelfEdges(self):
        n = self.getNumNodes()
        for i in range(n):
            self.addEdge(i, i)


def GenerateStochasticKron(initMat, k, deleteSelfLoopsForStats=False, directed=False, customEdges=False, edges=0):
    initN = initMat.getNumNodes()
    # get final size and make empty 'kroned' matrix
    nNodes = int(math.pow(initN, k))
    mtxDim = initMat.getNumNodes()
    mtxSum = initMat.getMtxSum()
    print(mtxSum)
    if (customEdges == True):
        nEdges = edges
        if (nEdges > (nNodes*nNodes)):
            raise ValueError("More edges than possible with number of Nodes")
    else:
        nEdges = math.pow(mtxSum, k)  # get number of predicted edges
    collisions = 0

    print(f'Edges = {nEdges}')
    print(f'Nodes = {nNodes}')

    # create vector for recursive matrix probability
    probToRCPosV = []
    cumProb = 0.0
    for i in range(mtxDim):
        for j in range(mtxDim):
            prob = initMat.getValue(i, j)
            if (prob > 0.0):
                cumProb += prob
                probToRCPosV.append((cumProb/mtxSum, i, j))
                # print "Prob Vector Value:" #testing
                # print cumProb/mtxSum #testing

    print(f'probToRC = {probToRCPosV}')
    # add Nodes
    finalGraph = np.zeros((nNodes, nNodes))
    # add Edges
    e = 0
    # print nEdges #testing
    while (e < nEdges):
        rng = nNodes
        row = 0
        col = 0
        for t in range(k):
            prob = random.uniform(0, 1)
            # print "prob:" #testing
            # print prob #testing
            n = 0
            while (prob > probToRCPosV[n][0]):  # make location
                n += 1
            mrow = probToRCPosV[n][1]
            mcol = probToRCPosV[n][2]
            rng /= mtxDim
            row += int(mrow * rng)
            col += int(mcol * rng)
        if (finalGraph[row, col] == 0):  # if there is no edge
            finalGraph[row, col] = 1
            e += 1
            if (not directed):  # symmetry if not directed
                if (row != col):
                    finalGraph[col, row] = 1
        else:
            collisions += 1
    print(f"Collisions =  {collisions}")

    # delete self loops if needed for stats
    if (deleteSelfLoopsForStats):
        finalGraph = deleteSelfLoops(finalGraph, nNodes)
    finalGraph = convert(finalGraph)
    return finalGraph


def get_graph(nxgraph):

    x = nxgraph
    cc_conn = nx.connected_components(x)
    num_cc = nx.number_connected_components(x)
    # largest_cc = len(cc_conn[0])

    return x, cc_conn, num_cc  # , largest_cc


def create_graph_stats(nxgraph):
    (x, cc_conn, num_cc) = get_graph(nxgraph)  # , largest_cc
    cc = nx.closeness_centrality(x)
    bc = nx.betweenness_centrality(x)
    deg = nx.degree_centrality(x)
    dens = nx.density(x)

    stats = {'cc': cc, 'bc': bc, 'deg': deg,
             'num_cc': num_cc, 'dens': dens}  # , 'largest_cc':largest_cc}

    return stats  # conn,


if __name__ == "__main__":

    nodes = 2

    init = InitMatrix(nodes)
    init.make()
    probArr = np.array([1, 0.3, 0.3, 0.2])
    init.makeStochasticCustom(probArr)

    k = 8
    print(f"Seed Matrix Nodes = {nodes}")
    print(f"Kronecker Iterations = {k}")
    edge_num = nodes ** k * 16
    nxgraph = GenerateStochasticKron(
        init, k, True, customEdges=True, edges=edge_num)
    # for line in nx.generate_edgelist(nxgraph, data=False):
    #   print(line)
    print("Done Creating Network!")

    is_bipart = nx.is_bipartite(nxgraph)
    print(f"is_bipart = {is_bipart}")
    is_conn = nx.is_connected(nxgraph)
    print(f"is_conn = {is_conn}")

    edges = nx.edges(nxgraph)
    print(f'len_edges = {len(edges)}')

    edge_array = np.array(nx.adjacency_matrix(nxgraph).todense())

    plt.imshow(edge_array)

    print(f'edge_array = {edge_array.shape}')

    plt.show()
