# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/task4_window_stop_runtime_closure_mainline/traffic_baseline_ablation.json`
- baseline_run_tag: `task4_window_stop_runtime_closure_mainline`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/task4_window_stop_runtime_closure_mainline/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/task4_window_stop_runtime_closure_mainline/window_stop_analysis/window_stop_2us_ablation.json, /home/xgy/remote/snn3dexp/analysis/codesign_matrix/task4_window_stop_runtime_closure_mainline/window_stop_analysis/window_stop_5us_ablation.json, /home/xgy/remote/snn3dexp/analysis/codesign_matrix/task4_window_stop_runtime_closure_mainline/window_stop_analysis/window_stop_10us_ablation.json`
- hotspot_runtime_summary_path: ``

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_2d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| memory_only_3d | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.500 | 0.000 | 0.000 |
| noc_only_3d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.500 | 0.000 | 0.000 |
| full_3d_monolithic_proxy | monolithic_like | 0 | 0 | 0 | 0 | 0 |  | 0.500 | 0.000 | 0.000 |
| full_3d_runtime_adaptive | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.094 | 0.000 | 0.000 |
| full_3d_tile_bundle_v3 | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.094 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 0 | 0 | 0.000 | 0 | NA | NA |
| traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 0 | 0 | 0 | 0.000 | 0 | 0.150 | 0.311 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | route_packetization | router_bundle_v3_rx_total | 0 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_bundle_v3_packets_total | 0 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_spikekey_v4_packets_total | 0 | NA |
| traffic_mem_bundle_vs_direct | processing_writeback | gas_scatter_spikes_emitted_total | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | home_access_class | tier_local_home_total_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | home_access_class | same_xy_cross_tier_total_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | home_access_class | remote_home_total_demands | 0 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | active_stack_utilization | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_memory_request_skew | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_bundle_vs_direct | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 0 | NA |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | tier_local_home_total_demands | 0 | NA |
| traffic_mem_monolithic_vs_hbm | home_access_class | same_xy_cross_tier_total_demands | 0 | NA |
| traffic_mem_monolithic_vs_hbm | home_access_class | remote_home_total_demands | 0 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | active_stack_utilization | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_memory_request_skew | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | 0.150 | NA |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | 0.311 | 2.228 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | 0.000 | NA |

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 448 | 149.333 | 30888.333 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 1256 | 628.000 | 44465.000 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 112.000 | 2368.000 |
| 4 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |
| 8 | full_3d_snn_window | hbm_like | 448 | 56.000 | 15786.125 |
| 8 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 185.500 | 25388.750 |
| 8 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 56.000 | 1600.000 |
| 8 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |
| 16 | full_3d_snn_window | hbm_like | 448 | 28.000 | 7925.062 |
| 16 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 92.750 | 12726.375 |
| 16 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 28.000 | 832.000 |
| 16 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 808 | 2.804 | 256 | 73 |
| 4 | sp64 | 1312 | 3.929 | 1497 | 428 |
| 8 | default | 1036 | 3.312 | 268 | 76 |
| 8 | sp64 | 1344 | 4.000 | 1512 | 432 |
| 16 | default | 1036 | 3.312 | 268 | 76 |
| 16 | sp64 | 1344 | 4.000 | 1512 | 432 |

### Window Gating vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Activation Delta | Gating Activation Delta | Unique Source Delta |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | default | -448 | 0.000 | 16 | 256 | 8 |
| 4 | sp64 | -448 | 0.000 | 64 | 448 | 8 |
| 8 | default | -448 | 0.000 | 16 | 256 | 8 |
| 8 | sp64 | -448 | 0.000 | 136 | 736 | 8 |
| 16 | default | -448 | 0.000 | 16 | 256 | 8 |
| 16 | sp64 | -448 | 0.000 | 280 | 1312 | 8 |

### Window Monolithic vs HBM
| Steps | Spike Budget | Memory Delta | Stall / Step Delta | Gather Delta | Stream Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 0 | -28520.333 | 0 | 0 |
| 4 | sp64 | 0 | -28520.333 | 0 | 0 |
| 8 | default | 0 | -14186.125 | 0 | 0 |
| 8 | sp64 | 0 | -14186.125 | 0 | 0 |
| 16 | default | 0 | -7093.062 | 0 | 0 |
| 16 | sp64 | 0 | -7093.062 | 0 | 0 |

### Window Spike Sensitivity
| Steps | Case | Spike Budget | Memory Delta | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 4 | full_3d_snn_window_bundle_v3 | sp64 | 504 | 1241 | 355 |
| 4 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 4 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 8 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 16 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |

## Long Stop-Window Overlap
| Stop | Case | Memory | Steps Completed | Memory Requests | Same Stack | Same Controller | Same Class |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  | full_3d_snn_window | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_bundle_v3 | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_monolithic_proxy | monolithic_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_bundle_v3 | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_monolithic_proxy | monolithic_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_bundle_v3 | hbm_like | 0 | 0 | False | False | False |
|  | full_3d_snn_window_monolithic_proxy | monolithic_like | 0 | 0 | False | False | False |

### Stop-Window Compare
| Stop | Compare | Memory Delta | Steps Delta | Same Stack Delta | Same Controller Delta | Same Class Delta |
| --- | --- | --- | --- | --- | --- | --- |
|  | window_stop_bundle_vs_direct | 0 | 0 | 0 | 0 | 0 |
|  | window_stop_monolithic_vs_direct | 0 | 0 | 0 | 0 | 0 |
|  | window_stop_bundle_vs_direct | 0 | 0 | 0 | 0 | 0 |
|  | window_stop_monolithic_vs_direct | 0 | 0 | 0 | 0 | 0 |
|  | window_stop_bundle_vs_direct | 0 | 0 | 0 | 0 | 0 |
|  | window_stop_monolithic_vs_direct | 0 | 0 | 0 | 0 | 0 |

## HotSpot Runtime Signals
| Compare | Vertical Link Delta | Hotspot Penalty Delta | Home-Route Adjustment Delta |
| --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | 0.000 | 0.000 | 2.000 |
