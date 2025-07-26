#!/usr/bin/env python3
"""
可视化4x4 mesh网格拓扑
"""

def visualize_mesh_topology():
    print("=== 4x4 Mesh 网格拓扑可视化 ===\n")
    
    MESH_SIZE_X = 4
    MESH_SIZE_Y = 4
    
    print("网格布局 (节点编号):")
    print("┌" + "─" * (MESH_SIZE_X * 8 - 1) + "┐")
    
    for y in range(MESH_SIZE_Y):
        line = "│"
        for x in range(MESH_SIZE_X):
            node_id = y * MESH_SIZE_X + x
            line += f" R{node_id:2d} "
            if x < MESH_SIZE_X - 1:
                line += "─"
        line += "│"
        print(line)
        
        if y < MESH_SIZE_Y - 1:
            # 打印垂直连接
            vert_line = "│"
            for x in range(MESH_SIZE_X):
                vert_line += "  │  "
                if x < MESH_SIZE_X - 1:
                    vert_line += " "
            vert_line += "│"
            print(vert_line)
    
    print("└" + "─" * (MESH_SIZE_X * 8 - 1) + "┘")
    
    print("\n网格连接说明:")
    print("- 每个 R## 代表一个路由器节点")
    print("- 水平线 (─) 表示东西方向的连接")
    print("- 垂直线 (│) 表示南北方向的连接")
    print("- 边缘节点连接数较少，内部节点有4个方向连接")
    
    print("\n端口映射:")
    print("- port0: 东方向 (+x)")
    print("- port1: 西方向 (-x)")
    print("- port2: 南方向 (+y)")
    print("- port3: 北方向 (-y)")
    print("- port4: 本地连接 (NIC)")
    
    print("\n节点分类:")
    corner_nodes = [0, 3, 12, 15]
    edge_nodes = [1, 2, 4, 7, 8, 11, 13, 14]
    inner_nodes = [5, 6, 9, 10]
    
    print(f"角落节点 (2条连接): {corner_nodes}")
    print(f"边缘节点 (3条连接): {edge_nodes}")
    print(f"内部节点 (4条连接): {inner_nodes}")
    
    print(f"\n总链路数计算:")
    print(f"- 水平链路: {MESH_SIZE_Y} 行 × {MESH_SIZE_X-1} 条/行 = {MESH_SIZE_Y * (MESH_SIZE_X-1)} 条")
    print(f"- 垂直链路: {MESH_SIZE_X} 列 × {MESH_SIZE_Y-1} 条/列 = {MESH_SIZE_X * (MESH_SIZE_Y-1)} 条")
    print(f"- 总计: {MESH_SIZE_Y * (MESH_SIZE_X-1) + MESH_SIZE_X * (MESH_SIZE_Y-1)} 条双向链路")

if __name__ == "__main__":
    visualize_mesh_topology()
