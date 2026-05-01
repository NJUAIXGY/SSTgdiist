#!/usr/bin/env python3

import os
import sst

"""
SpikeKey/SpikeTileKey native multicast end-to-end test (4x4 mesh):
  - Router: SnnDL.MulticastRouter (mesh)
  - NIC:    SnnDL.MulticastNIC
  - Core workload: workload_impl="traffic" (deterministic pseudo-random injection)

Modes:
  - Unicast(Spike): MULTICAST_ENABLE=0
  - Multicast(SpikeKey): MULTICAST_ENABLE=1 EXPERIMENTAL_SPIKETILE_ENABLE=0
  - Multicast(SpikeTileKey): MULTICAST_ENABLE=1 EXPERIMENTAL_SPIKETILE_ENABLE=1

Goal:
  - Validate that SpikeTileKey can traverse the full blocked-multicast backend
    (INTER->INTRA stage transition + in-block tree cloning) without losing its tail payload.
"""


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    try:
        return int(v, 0)
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v if v else default


def main() -> None:
    mesh_w = _env_int("MESH_W", 4)
    mesh_h = _env_int("MESH_H", 4)
    if mesh_w <= 0 or mesh_h <= 0:
        raise RuntimeError(f"invalid mesh shape: {mesh_w}x{mesh_h}")
    total_nodes = mesh_w * mesh_h

    cores_per_pe = _env_int("NUM_CORES_PER_PE", 4)
    neurons_per_core = _env_int("NEURONS_PER_CORE", 64)
    if cores_per_pe <= 0 or neurons_per_core <= 0:
        raise RuntimeError(f"invalid core layout: cores_per_pe={cores_per_pe} neurons_per_core={neurons_per_core}")
    neurons_per_pe = cores_per_pe * neurons_per_core
    total_neurons = total_nodes * neurons_per_pe

    sim_time = _env_str("SIM_TIME", "20us")
    link_latency = _env_str("LINK_LATENCY", "5ns")
    router_latency_cycles = _env_int("ROUTER_LATENCY_CYCLES", 0)
    router_serialize_enable = _env_int("ROUTER_SERIALIZE_ENABLE", 0)
    router_serialize_service_cycles = _env_int("ROUTER_SERIALIZE_SERVICE_CYCLES", 1)
    router_serialize_byte_enable = _env_int("ROUTER_SERIALIZE_BYTE_ENABLE", 0)
    router_serialize_bytes_per_cycle = _env_int("ROUTER_SERIALIZE_BYTES_PER_CYCLE", 16)
    router_serialize_header_bytes = _env_int("ROUTER_SERIALIZE_HEADER_BYTES", 24)
    router_verbose = _env_int("ROUTER_VERBOSE", 1)
    nic_verbose = _env_int("NIC_VERBOSE", 1)
    pe_verbose = _env_int("PE_VERBOSE", 1)
    noc_lat_hist_max = _env_int("NOC_LAT_HIST_MAX", 131072)

    edges_csv = _env_str(
        "EDGES_CSV",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "experimental_features", "native_multicast_lab", "edges", "mesh4x4_c4_n64_edges.csv"),
    )
    edges_csv = os.path.abspath(edges_csv)

    multicast_enable = _env_int("MULTICAST_ENABLE", 1)
    block_w = _env_int("MULTICAST_BLOCK_W", 2)
    block_h = _env_int("MULTICAST_BLOCK_H", 2)
    ingress_policy = _env_str("MULTICAST_INGRESS_POLICY", "top_left")
    inter_policy = _env_str("MULTICAST_INTER_POLICY", "xy")
    intra_policy = _env_str("MULTICAST_INTRA_POLICY", "manhattan_x_first")
    adaptive_telemetry_enable = _env_int("ADAPTIVE_TELEMETRY_ENABLE", 0)
    adaptive_inter_w_wait = _env_int("ADAPTIVE_INTER_W_WAIT", 1)
    adaptive_inter_w_service = _env_int("ADAPTIVE_INTER_W_SERVICE", 1)
    adaptive_inter_w_len = _env_int("ADAPTIVE_INTER_W_LEN", 0)
    adaptive_intra_w_bytes = _env_int("ADAPTIVE_INTRA_W_BYTES", 1)
    adaptive_intra_w_queue = _env_int("ADAPTIVE_INTRA_W_QUEUE", 1)

    # SpikeTileKey experimental knobs (sender-side aggregation).
    spiketile_enable = _env_int("EXPERIMENTAL_SPIKETILE_ENABLE", 0)
    spiketile_block_cols = _env_int("EXPERIMENTAL_SPIKETILE_BLOCK_COLS", 64)
    spiketile_max_pre_bits = _env_int("EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS", 64)
    compact_mask_enable = _env_int("EXPERIMENTAL_COMPACT_MASK_ENABLE", 0)
    inter_bundle_enable = _env_int("EXPERIMENTAL_INTER_BUNDLE_ENABLE", 0)
    inter_bundle_max_entries = _env_int("EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES", 64)
    inter_bundle_v2_enable = _env_int("EXPERIMENTAL_INTER_BUNDLE_V2_ENABLE", 0)
    local_endpoint_multicast_enable = _env_int("LOCAL_ENDPOINT_MULTICAST_ENABLE", 0)

    traffic_period_cycles = _env_int("TRAFFIC_PERIOD_CYCLES", 50)
    traffic_batch_size = _env_int("TRAFFIC_BATCH_SIZE", 8)
    traffic_seed = _env_int("TRAFFIC_SEED", 1)
    traffic_pre_begin = _env_int("TRAFFIC_PRE_BEGIN", 0)
    traffic_pre_end = _env_int("TRAFFIC_PRE_END", neurons_per_core)
    traffic_stop_cycle = _env_int("TRAFFIC_STOP_CYCLE", 0)

    traffic_src_node = _env_int("TRAFFIC_SRC_NODE", 0)
    traffic_src_core = _env_int("TRAFFIC_SRC_CORE", 0)
    traffic_enable_all = _env_int("TRAFFIC_ENABLE_ALL", 0) != 0

    mapping_assume_block_ids = _env_int("MAPPING_ASSUME_BLOCK_IDS", 0)
    routing_epsilon = float(os.environ.get("ROUTING_EPSILON", "1e-8").strip() or "1e-8")
    routing_topk = _env_int("ROUTING_TOPK", 0)
    routing_topk_per_pe = _env_int("ROUTING_TOPK_PER_PE", 0)

    core_quiet_finish = _env_int("CORE_QUIET_FINISH", 1)
    spikekey_check_enable = _env_int("SPIKEY_CHECK_ENABLE", 1)
    spikekey_check_fatal = _env_int("SPIKEY_CHECK_FATAL", 1)
    spikekey_check_log_cap = _env_int("SPIKEY_CHECK_LOG_CAP", 8)
    spikekey_group_log_cap = _env_int("SPIKEY_GROUP_LOG_CAP", 8)

    # Routers
    routers = []
    for node_id in range(total_nodes):
        r = sst.Component(f"router_{node_id}", "SnnDL.MulticastRouter")
        r.addParams(
            {
                "node_id": node_id,
                "mesh_shape": f"{mesh_w}x{mesh_h}",
                "router_latency_cycles": router_latency_cycles,
                "serialize_output_enable": router_serialize_enable,
                "serialize_service_cycles": router_serialize_service_cycles,
                "serialize_output_byte_enable": router_serialize_byte_enable,
                "serialize_bytes_per_cycle": router_serialize_bytes_per_cycle,
                "serialize_header_bytes": router_serialize_header_bytes,
                "local_endpoint_multicast_enable": local_endpoint_multicast_enable,
                "multicast_inter_policy": inter_policy,
                "multicast_intra_policy": intra_policy,
                "adaptive_telemetry_enable": adaptive_telemetry_enable,
                "adaptive_inter_w_wait": adaptive_inter_w_wait,
                "adaptive_inter_w_service": adaptive_inter_w_service,
                "adaptive_inter_w_len": adaptive_inter_w_len,
                "adaptive_intra_w_bytes": adaptive_intra_w_bytes,
                "adaptive_intra_w_queue": adaptive_intra_w_queue,
                "verbose": router_verbose,
            }
        )
        routers.append(r)

    # PEs + NICs + cores
    nics = []
    for node_id in range(total_nodes):
        pe = sst.Component(f"multicore_pe_{node_id}", "SnnDL.MultiCorePE")
        pe.addParams(
            {
                "verbose": 0,
                "primary_keepalive": 0,
                "manual_core_drive_enable": 0,
                "node_id": node_id,
                "total_nodes": total_nodes,
                "num_cores": cores_per_pe,
                "neurons_per_core": neurons_per_core,
                "neurons_per_pe": neurons_per_pe,
                "total_neurons": total_neurons,
                "global_neuron_base": node_id * neurons_per_pe,
                "noc_lat_hist_max": noc_lat_hist_max,
                # For traffic-only experiments: keep StepActivation off (MultiCorePE forces off for workload_impl=traffic).
                "step_activation_enable": 0,
                "enable_test_traffic": 0,
                "verbose": pe_verbose,
            }
        )

        nic = pe.setSubComponent("network_interface", "SnnDL.MulticastNIC")
        nic.addParams(
            {
                "node_id": str(node_id),
                "port_name": "network",
                "stats_header_bytes": router_serialize_header_bytes,
                "local_endpoint_multicast_enable": local_endpoint_multicast_enable,
                "verbose": nic_verbose,
            }
        )
        nics.append(nic)

        for core_id in range(cores_per_pe):
            core_base = node_id * neurons_per_pe + core_id * neurons_per_core
            traffic_enable = traffic_enable_all or (node_id == traffic_src_node and core_id == traffic_src_core)

            core = pe.setSubComponent(f"core{core_id}", "SnnDL.SnnPESubComponent")
            core.addParams(
                {
                    "node_id": node_id,
                    "core_id": core_id,
                    "total_cores": cores_per_pe,
                    "total_nodes": total_nodes,
                    "num_neurons": neurons_per_core,
                    "neurons_per_pe": neurons_per_pe,
                    "global_neuron_base": core_base,
                    "use_event_weight_fallback": 0,
                    "enable_weight_fetch": 0,
                    "quiet_finish_logs": core_quiet_finish,
                    "traffic_spikekey_check_enable": spikekey_check_enable,
                    "traffic_spikekey_check_fatal": spikekey_check_fatal,
                    "traffic_spikekey_check_log_cap": spikekey_check_log_cap,
                    "traffic_spikekey_group_log_cap": spikekey_group_log_cap,
                    # Route build (edges CSV)
                    "routing_mode": "weight_driven",
                    "routing_epsilon": routing_epsilon,
                    "routing_topk": routing_topk,
                    "routing_topk_per_pe": routing_topk_per_pe,
                    "mapping_mode": "edges_csv",
                    "mapping_edges_file": edges_csv,
                    "mapping_csv_has_header": 1,
                    "mapping_csv_separator": ",",
                    "mapping_assume_block_ids": mapping_assume_block_ids,
                    # Multicast config (blocked multicast)
                    "multicast_enable": multicast_enable,
                    "multicast_block_w": block_w,
                    "multicast_block_h": block_h,
                    "multicast_ingress_policy": ingress_policy,
                    "multicast_inter_policy": inter_policy,
                    "multicast_intra_policy": intra_policy,
                    # Experimental tile aggregation knobs
                    "experimental_spiketile_enable": 1 if spiketile_enable else 0,
                    "experimental_spiketile_block_cols": int(spiketile_block_cols),
                    "experimental_spiketile_max_pre_bits": int(spiketile_max_pre_bits),
                    "experimental_compact_mask_enable": int(compact_mask_enable),
                    "experimental_inter_bundle_enable": int(inter_bundle_enable),
                    "experimental_inter_bundle_max_entries": int(inter_bundle_max_entries),
                    "experimental_inter_bundle_v2_enable": int(inter_bundle_v2_enable),
                    # Workload selection + traffic injection
                    "workload_impl": "traffic",
                    "traffic_enable": 1 if traffic_enable else 0,
                    "traffic_period_cycles": traffic_period_cycles,
                    "traffic_batch_size": traffic_batch_size,
                    "traffic_seed": traffic_seed,
                    "traffic_pre_begin": traffic_pre_begin,
                    "traffic_pre_end": traffic_pre_end,
                    "traffic_stop_cycle": traffic_stop_cycle,
                }
            )

    # Connect router mesh (bidirectional links)
    for y in range(mesh_h):
        for x in range(mesh_w):
            node_id = y * mesh_w + x
            if x + 1 < mesh_w:
                east_id = y * mesh_w + (x + 1)
                l = sst.Link(f"link_e_{node_id}_{east_id}")
                l.connect((routers[node_id], "east", link_latency), (routers[east_id], "west", link_latency))
            if y + 1 < mesh_h:
                south_id = (y + 1) * mesh_w + x
                l = sst.Link(f"link_s_{node_id}_{south_id}")
                l.connect((routers[node_id], "south", link_latency), (routers[south_id], "north", link_latency))

    # Connect NIC <-> local router
    for node_id in range(total_nodes):
        l = sst.Link(f"link_local_{node_id}")
        l.connect((nics[node_id], "network", link_latency), (routers[node_id], "local", link_latency))

    sst.setProgramOption("timebase", "1ps")
    sst.setProgramOption("stop-at", sim_time)

    print(f"[keytile-mcast] mesh={mesh_w}x{mesh_h} nodes={total_nodes} cores_per_pe={cores_per_pe} npc={neurons_per_core} sim={sim_time}")
    print(f"[keytile-mcast] edges_csv={edges_csv} mapping_assume_block_ids={mapping_assume_block_ids}")
    print(f"[keytile-mcast] multicast_enable={multicast_enable} block={block_w}x{block_h} ingress={ingress_policy}")
    print(f"[keytile-mcast] policies: inter={inter_policy} intra={intra_policy}")
    print(
        f"[keytile-mcast] adaptive: telemetry={adaptive_telemetry_enable}"
        f" inter_w(wait/service/len)={adaptive_inter_w_wait}/{adaptive_inter_w_service}/{adaptive_inter_w_len}"
        f" intra_w(bytes/queue)={adaptive_intra_w_bytes}/{adaptive_intra_w_queue}"
    )
    print(
        f"[keytile-mcast] spiketile: enable={1 if spiketile_enable else 0} block_cols={spiketile_block_cols} max_pre_bits={spiketile_max_pre_bits}"
    )
    print(f"[keytile-mcast] compact_mask_enable={1 if compact_mask_enable else 0}")
    print(
        f"[keytile-mcast] inter_bundle: enable={1 if inter_bundle_enable else 0}"
        f" max_entries={inter_bundle_max_entries} v2={1 if inter_bundle_v2_enable else 0}"
    )
    print(f"[keytile-mcast] local_endpoint_multicast_enable={1 if local_endpoint_multicast_enable else 0}")
    print(
        f"[keytile-mcast] traffic: enable_all={1 if traffic_enable_all else 0} src_node={traffic_src_node} src_core={traffic_src_core}"
        f" period_cycles={traffic_period_cycles} batch={traffic_batch_size} seed={traffic_seed}"
    )
    print(
        f"[keytile-mcast] router: lat_cycles={router_latency_cycles} serialize={router_serialize_enable}"
        f" service_cycles={router_serialize_service_cycles} byte_serialize={router_serialize_byte_enable}"
        f" bytes_per_cycle={router_serialize_bytes_per_cycle} header_bytes={router_serialize_header_bytes}"
    )


if __name__ == "__main__":
    main()
