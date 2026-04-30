# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/traffic_baseline_ablation.json`
- baseline_run_tag: `matrix23_phase2_mainline_runtime_traffic`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: ``
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/phase2_route_runtime_refresh_20260324/matrix23_phase2_mainline_runtime_smoke/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_2d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| memory_only_3d | hbm_like | 3068 | 1024 | 1024 | 512 | 1537 | remote_home | 0.500 | 0.000 | 0.000 |
| noc_only_3d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d | hbm_like | 3068 | 1024 | 1024 | 512 | 1537 | remote_home | 0.500 | 0.000 | 0.000 |
| full_3d_monolithic_proxy | monolithic_like | 6144 | 1024 | 1024 | 512 | 0 | same_xy_cross_tier | 0.500 | 0.000 | 0.000 |
| full_3d_tile_bundle_v3 | hbm_like | 3268 | 2814 | 2814 | 1407 | 6812 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 200 | 5275 | -498 | 0.000 | 1362 | NA | NA |
| traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 3076 | -1537 | -832 | 0.000 | -397 | -0.087 | 0.003 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | route_packetization | router_bundle_v3_rx_total | 1440 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_bundle_v3_packets_total | 512 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_spikekey_v4_packets_total | -896 | 0.000 |
| traffic_mem_bundle_vs_direct | processing_writeback | gas_scatter_spikes_emitted_total | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_demands | 895 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_backlog | 678 | 4.213 |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_demands | 1790 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_backlog | 1827 | 4.589 |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_demands | 1790 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_backlog | 1879 | 4.435 |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_demands | 895 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_backlog | 891 | 4.300 |
| traffic_mem_bundle_vs_direct | home_access_class | tier_local_home_total_demands | 916 | 2.789 |
| traffic_mem_bundle_vs_direct | home_access_class | same_xy_cross_tier_total_demands | 3162 | 7.176 |
| traffic_mem_bundle_vs_direct | home_access_class | remote_home_total_demands | -498 | 0.514 |
| traffic_mem_bundle_vs_direct | home_pressure | tier_local_home_service_deficit_attribution | 944.269 | 4.577 |
| traffic_mem_bundle_vs_direct | home_pressure | same_xy_cross_tier_service_deficit_attribution | 2844.669 | 11.775 |
| traffic_mem_bundle_vs_direct | home_pressure | remote_home_service_deficit_attribution | -82.937 | 0.843 |
| traffic_mem_bundle_vs_direct | home_pressure | attributed_service_deficit_total | 3706.000 | 4.509 |
| traffic_mem_bundle_vs_direct | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_stack_service_deficit | 1362 | 4.431 |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_controller_service_deficit_proxy | 340.500 | 4.431 |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_memory_request_skew | 0.002 | 1.002 |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_service_deficit_skew | -0.000 | 1.000 |
| traffic_mem_bundle_vs_direct | service | total_service_deficit | 5275 | 4.432 |
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 3076 | 2.003 |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | -1537 | 0.000 |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | -0.746 | 0.000 |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | tier_local_home_total_demands | 0 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | same_xy_cross_tier_total_demands | 832 | 2.625 |
| traffic_mem_monolithic_vs_hbm | home_access_class | remote_home_total_demands | -832 | 0.188 |
| traffic_mem_monolithic_vs_hbm | home_pressure | tier_local_home_service_deficit_attribution | -264.000 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_pressure | same_xy_cross_tier_service_deficit_attribution | -264.000 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_pressure | remote_home_service_deficit_attribution | -528.000 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_pressure | attributed_service_deficit_total | -1056.000 | 0.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_stack_service_deficit | -397 | 0.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_controller_service_deficit_proxy | -99.250 | 0.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_memory_request_skew | -0.010 | 0.990 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_service_deficit_skew | -1.033 | 0.000 |
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | -0.087 | 0.633 |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | 0.003 | 1.006 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | 0.000 | NA |

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 234 | 234.000 | 28324.000 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 416 | 104.000 | 2808.000 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 912 | 912.000 | 34852.000 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 678 | 3.897 | 258 | 88 |

### Window Monolithic vs HBM
| Steps | Spike Budget | Memory Delta | Stall / Step Delta | Gather Delta | Stream Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 182 | -25516.000 | 0 | 64 |

### Window Spike Sensitivity
_None_

## Long Stop-Window Overlap
_None_

### Stop-Window Compare
_None_

## HotSpot Runtime Signals
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (6 cases)
_None_
