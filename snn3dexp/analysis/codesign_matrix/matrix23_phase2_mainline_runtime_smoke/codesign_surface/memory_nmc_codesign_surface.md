# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/traffic_baseline_ablation.json`
- baseline_run_tag: `matrix23_phase2_mainline_runtime_traffic`
- baseline_overlay_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/windowed_controller_runtime_refresh_20260322_ablation.json`
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/long_window_ablation_controller_runtime_refresh_20260322/window_stop_2us_ablation.json, /home/xgy/remote/snn3dexp/analysis/long_window_ablation_controller_runtime_refresh_20260322/window_stop_10us_ablation.json`
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/full_3d_runtime_adaptive/arc4_hotspot_refresh_20260321/runtime_summary.json`

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
| traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 182 | 0 | 96 | 0.000 | 0 | -0.292 | -0.036 |

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
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 182 | 1.778 |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | -0.487 | 0.000 |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | -0.406 | 0.381 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.406 | 5.333 |
| traffic_mem_monolithic_vs_hbm | home_access_class | tier_local_home_total_demands | 128 | 3.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | same_xy_cross_tier_total_demands | -64 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | remote_home_total_demands | 96 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_memory_request_skew | -0.004 | 0.996 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | -0.292 | 0.339 |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | -0.036 | 0.938 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | -219.143 | 0.063 |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | -27760.857 | 0.020 |

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
| Stop | Case | Memory | Steps Completed | Memory Requests | Same Stack | Same Controller | Same Class |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2us | full_3d_snn_window | hbm_like | 1 | 234 | False | False | False |
| 2us | full_3d_snn_window_monolithic_proxy | monolithic_like | 28 | 416 | False | False | False |
| 2us | full_3d_snn_window_bundle_v3 | hbm_like | 1 | 912 | False | False | False |
| 10us | full_3d_snn_window | hbm_like | 25 | 416 | False | False | False |
| 10us | full_3d_snn_window_monolithic_proxy | monolithic_like | 250 | 416 | False | False | False |
| 10us | full_3d_snn_window_bundle_v3 | hbm_like | 89 | 1020 | True | True | True |

### Stop-Window Compare
| Stop | Compare | Memory Delta | Steps Delta | Same Stack Delta | Same Controller Delta | Same Class Delta |
| --- | --- | --- | --- | --- | --- | --- |
| 2us | window_stop_bundle_vs_direct | 678 | 0 | 0 | 0 | 0 |
| 2us | window_stop_monolithic_vs_direct | 182 | 27 | 0 | 0 | 0 |
| 10us | window_stop_bundle_vs_direct | 604 | 64 | 1 | 1 | 1 |
| 10us | window_stop_monolithic_vs_direct | 0 | 225 | 0 | 0 | 0 |

## HotSpot Runtime Signals
_None_
