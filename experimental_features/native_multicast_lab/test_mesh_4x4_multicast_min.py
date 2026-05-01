#!/usr/bin/env python3

import os
import sst

"""
Minimal 4x4 mesh connectivity test using SnnDL native router mesh:
  - Router: SnnDL.MulticastRouter
  - NIC:    SnnDL.MulticastNIC
  - Traffic: MultiCorePE built-in enable_test_traffic (deterministic external spikes)

Goal (Phase-0): validate end-to-end mesh wiring and packet delivery without GAS/memHierarchy/WeightLoader.
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

    num_cores = _env_int("NUM_CORES_PER_PE", 4)
    neurons_per_core = _env_int("NEURONS_PER_CORE", 64)
    if num_cores <= 0 or neurons_per_core <= 0:
        raise RuntimeError(f"invalid core layout: num_cores={num_cores} neurons_per_core={neurons_per_core}")
    neurons_per_pe = num_cores * neurons_per_core

    sim_time = _env_str("MESH_SIM_TIME", "10us")
    link_latency = _env_str("MESH_LINK_LATENCY", "5ns")
    router_latency_cycles = _env_int("ROUTER_LATENCY_CYCLES", 0)

    # NOTE: SnnDL MultiCorePE creates core subcomponents during init(); explicitly enabling
    # per-instance stats can trigger SST core restrictions ("must be registered on creation").
    # Keep this script stats-free by default; enable stats only once we standardize a safe pattern.

    # Routers
    routers = []
    for node_id in range(total_nodes):
        r = sst.Component(f"router_{node_id}", "SnnDL.MulticastRouter")
        r.addParams({
            "node_id": node_id,
            "mesh_shape": f"{mesh_w}x{mesh_h}",
            "router_latency_cycles": router_latency_cycles,
            "verbose": 0,
        })
        routers.append(r)

    # PEs + NICs
    nodes = []
    nics = []
    test_target_node = _env_int("TEST_TARGET_NODE", total_nodes - 1)
    test_source_node = _env_int("TEST_SOURCE_NODE", 0)
    test_period = _env_int("TEST_PERIOD", 100)
    test_spikes_per_burst = _env_int("TEST_SPIKES_PER_BURST", 1)
    test_max_spikes = _env_int("TEST_MAX_SPIKES", 64)
    test_weight = float(os.environ.get("TEST_WEIGHT", "1.0").strip() or "1.0")

    # Optional: StepActivation (local-only unless BCSR routes enabled; kept off by default)
    step_enable = _env_int("STEP_ENABLE", 0) != 0
    step_period = _env_int("STEP_PERIOD_CYCLES", 0)
    step_fraction = float(os.environ.get("STEP_FRACTION", "0.0").strip() or "0.0")
    step_fanout = _env_int("STEP_FANOUT", 0)
    step_seed = _env_int("STEP_SEED", 271828)

    pe_verbose = _env_int("PE_VERBOSE", 0)
    pe_verbose_node = _env_int("PE_VERBOSE_NODE", -1)
    progress_log_interval_ns = _env_int("PROGRESS_LOG_INTERVAL_NS", 0)
    progress_log_node = _env_int("PROGRESS_LOG_NODE", -1)

    for node_id in range(total_nodes):
        base = node_id * neurons_per_pe
        node_verbose = pe_verbose if (pe_verbose_node < 0 or pe_verbose_node == node_id) else 0

        pe = sst.Component(f"multicore_pe_{node_id}", "SnnDL.MultiCorePE")
        pe.addParams({
            "verbose": node_verbose,
            "primary_keepalive": 0,
            "manual_core_drive_enable": 0,
            "node_id": node_id,
            "total_nodes": total_nodes,
            "num_cores": num_cores,
            "neurons_per_core": neurons_per_core,
            "neurons_per_pe": neurons_per_pe,
            "total_neurons": total_nodes * neurons_per_pe,
            "global_neuron_base": base,
            # Deterministic external traffic generator (exercises router mesh)
            "enable_test_traffic": 1 if node_id == test_source_node else 0,
            "test_target_node": test_target_node,
            "test_period": test_period,
            "test_spikes_per_burst": test_spikes_per_burst,
            "test_max_spikes": test_max_spikes,
            "test_weight": test_weight,
            # Optional progress log (helps confirm packets are arriving/being drained)
            "progress_log_interval_ns": int(progress_log_interval_ns),
            "progress_log_node": int(progress_log_node),
            # Keep StepActivation off by default (does not require GAS when period_cycles>0)
            "step_activation_enable": 1 if step_enable else 0,
            "step_activation_period_cycles": int(step_period),
            "step_activation_fraction": float(step_fraction),
            "step_activation_fanout": int(step_fanout),
            "step_activation_seed": int(step_seed),
            "step_reset_mem_each_step": 0,
            # Light diagnostics (optional via env)
            "step_diag_enable": _env_int("STEP_DIAG_ENABLE", 0),
            "step_diag_cap": _env_int("STEP_DIAG_CAP", 0),
        })

        nic = pe.setSubComponent("network_interface", "SnnDL.MulticastNIC")
        nic.addParams({
            "node_id": str(node_id),
            "port_name": "network",
            "verbose": _env_int("NIC_VERBOSE", 0),
        })

        # Cores: minimal SNN workload config; disable memory weight fetch to keep the test NoC-only.
        for core_idx in range(num_cores):
            core = pe.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
            core.addParams({
                "core_id": core_idx,
                "total_cores": num_cores,
                "node_id": node_id,
                "neurons_per_pe": neurons_per_pe,
                "global_neuron_base": base + core_idx * neurons_per_core,
                "num_neurons": neurons_per_core,
                # Avoid unintended firing feedback loops in a connectivity test
                "v_thresh": 1e30,
                "v_reset": 0.0,
                "v_rest": 0.0,
                "tau_mem": 20.0,
                "t_ref": 2,
                "enable_weight_fetch": 0,
                "use_event_weight_fallback": 0,
            })

        nodes.append(pe)
        nics.append(nic)

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

    print(f"[mesh-min] start: mesh={mesh_w}x{mesh_h} nodes={total_nodes} cores={num_cores} npc={neurons_per_core} sim={sim_time}")
    print(f"[mesh-min] traffic: src_node={test_source_node} target_node={test_target_node} period={test_period} burst={test_spikes_per_burst} max={test_max_spikes}")
    if step_enable:
        print(f"[mesh-min] step: enable=1 period_cycles={step_period} fraction={step_fraction} fanout={step_fanout} seed={step_seed}")
    else:
        print("[mesh-min] step: enable=0")


if __name__ == "__main__":
    main()
