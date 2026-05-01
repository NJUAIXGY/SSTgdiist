#!/usr/bin/env python3

import sst
import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from _common_2x2 import build_2x2, attach_nic, connect_nics_to_routers

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV")
sst.setStatisticOutputOptions({"filepath": "./neuron_dynamics_2x2_adex_stats.csv", "separator": ","})
sst.enableAllStatisticsForComponentType("SnnDL.MultiCorePE")
sst.enableAllStatisticsForComponentType("SnnDL.SpikeSource")
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent")

MESH_BW = "40GiB/s"; BUF_SZ = "4KiB"; TOTAL_NODES = 4
NUM_CORES_PER_PE = 1; NEURONS_PER_CORE = 8; NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE
base_dir = os.path.dirname(os.path.abspath(__file__))
edges_csv = os.path.join(base_dir, "edges_2x2.csv")
spike_file = os.path.join(base_dir, "spikes_pe0_strong.txt")

routers = build_2x2(MESH_BW, BUF_SZ)
nodes = []; nics = []
for i in range(TOTAL_NODES):
    node = sst.Component(f"multicore_pe_{i}", "SnnDL.MultiCorePE")
    node.addParams({
        "verbose": 0,
        "print_node_summary": 1,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "total_neurons": TOTAL_NODES * NEURONS_PER_PE,
        "node_id": i,
        "global_neuron_base": i * NEURONS_PER_PE,
        "enable_memory_weights": 0,
        "write_weights_on_init": 0,
        "v_thresh": -40.0,
        "v_reset": -58.0,
        "v_rest": -70.0,
    })
    core = node.setSubComponent("core0", "SnnDL.SnnPESubComponent")
    core.addParams({
        "core_id": 0,
        "total_cores": NUM_CORES_PER_PE,
        "global_neuron_base": i * NEURONS_PER_PE,
        "num_neurons": NEURONS_PER_PE,
        "v_thresh": -40.0,
        "v_reset": -58.0,
        "v_rest": -70.0,
        "tau_mem": 20.0,
        "t_ref": 2,
        "node_id": i,
        "verbose": 0,
        # neuron dynamics: AdEx
        "neuron_model": "AdEx",
        "neuron_dt_ms": 1.0,
        "model.C": 200.0,
        "model.gL": 10.0,
        "model.EL": -70.0,
        "model.VT": -50.0,
        "model.DeltaT": 2.0,
        "model.tau_w": 100.0,
        "model.a": 2.0,
        "model.b": 60.0,
        "model.Vr": -58.0,
        # weights/event
        "enable_weight_fetch": 0,
        "use_event_weight_fallback": 1,
        # routing via CSV edges
        "routing_mode": "weight_driven",
        "total_nodes": TOTAL_NODES,
        "mapping_mode": "edges_csv",
        "mapping_edges_file": edges_csv,
        "mapping_csv_has_header": 1,
        "mapping_csv_separator": ",",
        "mapping_assume_block_ids": 1,
        "route_exclude_self_pe": 0,
        "route_layers_mask": "",
        "routing_epsilon": 1e-6,
        "routing_topk": 0,
        "routing_topk_per_pe": 0,
    })
    nic = attach_nic(node, i, TOTAL_NODES, MESH_BW, BUF_SZ)
    nodes.append(node); nics.append(nic)

connect_nics_to_routers(nics, routers)

src = sst.Component("spike_source_0", "SnnDL.SpikeSource")
src.addParams({
    "verbose": 0,
    "dataset_path": spike_file,
    "neurons_per_core": NEURONS_PER_CORE,
    "num_cores": NUM_CORES_PER_PE,
    "event_weight": 100.0,
    "start_time_us": 0.0,
    "loop_dataset": 0,
})
sst.Link("spike_source_0_to_pe_0").connect((src, "spike_output", "5ns"), (nodes[0], "external_spike_input", "5ns"))

for n in nodes:
    n.enableStatistics(["total_external_spikes_received","total_internal_spikes_processed","total_network_spikes_sent","total_neuron_activations","memory_accesses"]) 
for r in routers:
    r.enableStatistics(["router.packet_count","router.network_load"]) 

sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", "500us")
