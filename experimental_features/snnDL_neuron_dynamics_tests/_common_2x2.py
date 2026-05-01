import sst
import os

def build_2x2(mesh_bw="40GiB/s", buffer_size="4KiB"):
    MESH_SIZE = 2
    TOTAL_NODES = 4
    routers = []
    for i in range(TOTAL_NODES):
        r = sst.Component(f"router_{i}", "merlin.hr_router")
        r.addParams({
            "id": i,
            "num_ports": 5,
            "link_bw": mesh_bw,
            "flit_size": "8B",
            "xbar_bw": mesh_bw,
            "input_latency": "10ns",
            "output_latency": "10ns",
            "input_buf_size": buffer_size,
            "output_buf_size": buffer_size,
            "num_vns": 1,
            "xbar_arb": "merlin.xbar_arb_lru",
            "debug": 0,
            "verbose": 0,
        })
        topo = r.setSubComponent("topology", "merlin.mesh")
        topo.addParams({"shape": f"{MESH_SIZE}x{MESH_SIZE}", "width": "1x1", "local_ports": "1"})
        routers.append(r)

    # mesh links
    for y in range(MESH_SIZE):
        for x in range(MESH_SIZE - 1):
            a = y * MESH_SIZE + x
            b = y * MESH_SIZE + (x + 1)
            link = sst.Link(f"router_east_{a}_to_{b}")
            link.connect((routers[a], "port0", "5ns"), (routers[b], "port1", "5ns"))
    for x in range(MESH_SIZE):
        for y in range(MESH_SIZE - 1):
            a = y * MESH_SIZE + x
            b = (y + 1) * MESH_SIZE + x
            link = sst.Link(f"router_south_{a}_to_{b}")
            link.connect((routers[a], "port2", "5ns"), (routers[b], "port3", "5ns"))
    return routers

def attach_nic(node, node_id, total_nodes, mesh_bw, buffer_size):
    nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
    nic.addParams({
        "node_id": str(node_id),
        "link_bw": mesh_bw,
        "input_buf_size": buffer_size,
        "output_buf_size": buffer_size,
        "use_direct_link": "false",
        "port_name": "network",
        "verbose": 0,
        "total_nodes": total_nodes,
    })
    return nic

def connect_nics_to_routers(nics, routers):
    for i, nic in enumerate(nics):
        link = sst.Link(f"nic_{i}_to_router_{i}")
        link.connect((nic, "network", "5ns"), (routers[i], "port4", "5ns"))

