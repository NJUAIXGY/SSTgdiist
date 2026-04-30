# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_single_20us_20260322_ablation.json`
- baseline_run_tag: `codesign_single_20us_20260322`
- baseline_overlay_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/codesign_single_20us_20260322_ablation_runtime_refresh.json`
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_2us_ablation.json, /home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_10us_ablation.json, /home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_20us_ablation.json`
- hotspot_runtime_summary_path: ``

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_2d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| memory_only_3d | hbm_like | 58560 | 40000 | 40000 | 20000 | 90726 | remote_home | 0.500 | 0.000 | 0.000 |
| noc_only_3d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d | hbm_like | 58560 | 40000 | 40000 | 20000 | 90726 | remote_home | 0.500 | 0.000 | 0.000 |
| full_3d_monolithic_proxy | monolithic_like | 159744 | 40000 | 40000 | 20000 | 40128 | same_xy_cross_tier | 0.500 | 0.000 | 0.000 |
| full_3d_mapping | hbm_like | 58560 | 40000 | 40000 | 20000 | 90726 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| full_3d_thermal_guard | hbm_like | 58560 | 40000 | 40000 | 20000 | 90726 | same_xy_cross_tier | 0.250 | 0.000 | 0.000 |
| full_3d_runtime_adaptive | hbm_like | 58560 | 40000 | 40000 | 20000 | 90726 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| full_3d_tile_bundle_v3 | hbm_like | 58560 | 109174 | 109174 | 54587 | 298248 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| noc_only_3d_bundle_fault_v3 | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | -19544 | 0.000 | 52014 | NA | NA |
| traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 | 96 | 0.000 | 0 | -0.294 | -0.039 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | route_packetization | router_bundle_v3_rx_total | 56250 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_bundle_v3_packets_total | 20000 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_spikekey_v4_packets_total | -35000 | 0.000 |
| traffic_mem_bundle_vs_direct | processing_writeback | gas_scatter_spikes_emitted_total | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_demands | 34587 | 2.729 |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_backlog | 34587 | 4.773 |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_demands | 69174 | 2.729 |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_backlog | 69174 | 3.256 |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_demands | 69174 | 2.729 |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_backlog | 69174 | 2.997 |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_demands | 34587 | 2.729 |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_backlog | 34587 | 3.128 |
| traffic_mem_bundle_vs_direct | home_access_class | tier_local_home_total_demands | 34590 | 2.729 |
| traffic_mem_bundle_vs_direct | home_access_class | same_xy_cross_tier_total_demands | 123302 | 7.165 |
| traffic_mem_bundle_vs_direct | home_access_class | remote_home_total_demands | -19544 | 0.511 |
| traffic_mem_bundle_vs_direct | home_pressure | tier_local_home_service_deficit_attribution | 34589.798 | 3.119 |
| traffic_mem_bundle_vs_direct | home_pressure | same_xy_cross_tier_service_deficit_attribution | 117331.001 | 8.187 |
| traffic_mem_bundle_vs_direct | home_pressure | remote_home_service_deficit_attribution | -13572.799 | 0.584 |
| traffic_mem_bundle_vs_direct | home_pressure | attributed_service_deficit_total | 138348.000 | 3.119 |
| traffic_mem_bundle_vs_direct | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_stack_service_deficit | 52014 | 3.279 |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_controller_service_deficit_proxy | 13003.500 | 3.279 |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_memory_request_skew | 0.000 | 1.000 |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_service_deficit_skew | -0.003 | 0.997 |
| traffic_mem_bundle_vs_direct | service | total_service_deficit | 207522 | 3.287 |
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 0 | 1.000 |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | -0.406 | 0.381 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.406 | 5.333 |
| traffic_mem_monolithic_vs_hbm | home_access_class | tier_local_home_total_demands | 96 | 2.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | same_xy_cross_tier_total_demands | -96 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | remote_home_total_demands | 96 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_memory_request_skew | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | -0.294 | 0.338 |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | -0.039 | 0.932 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | -0.585 | 0.574 |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | -429.577 | 0.174 |

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 416 | 104.000 | 26494.500 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 416 | 104.000 | 2808.000 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 1020 | 255.000 | 26621.500 |
| 8 | full_3d_snn_window | hbm_like | 416 | 52.000 | 17328.750 |
| 8 | full_3d_snn_window_monolithic_proxy | monolithic_like | 416 | 52.000 | 1803.000 |
| 8 | full_3d_snn_window_bundle_v3 | hbm_like | 1020 | 127.500 | 13342.750 |
| 16 | full_3d_snn_window | hbm_like | 416 | 26.000 | 8696.375 |
| 16 | full_3d_snn_window_monolithic_proxy | monolithic_like | 416 | 26.000 | 933.500 |
| 16 | full_3d_snn_window_bundle_v3 | hbm_like | 1020 | 63.750 | 6703.375 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 604 | 2.452 | 258 | 88 |
| 4 | sp64 | 864 | 3.077 | 1543 | 546 |
| 8 | default | 604 | 2.452 | 258 | 88 |
| 8 | sp64 | 888 | 3.135 | 1543 | 546 |
| 16 | default | 604 | 2.452 | 258 | 88 |
| 16 | sp64 | 888 | 3.135 | 1543 | 546 |

### Window Monolithic vs HBM
| Steps | Spike Budget | Memory Delta | Stall / Step Delta | Gather Delta | Stream Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 0 | -23686.500 | 0 | 0 |
| 4 | sp64 | 0 | -23686.500 | 0 | 0 |
| 8 | default | 0 | -15525.750 | 0 | 0 |
| 8 | sp64 | 0 | -15525.750 | 0 | 0 |
| 16 | default | 0 | -7762.875 | 0 | 0 |
| 16 | sp64 | 0 | -7762.875 | 0 | 0 |

### Window Spike Sensitivity
| Steps | Case | Spike Budget | Memory Delta | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 4 | full_3d_snn_window_bundle_v3 | sp64 | 260 | 1285 | 458 |
| 4 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_bundle_v3 | sp64 | 284 | 1285 | 458 |
| 8 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_bundle_v3 | sp64 | 284 | 1285 | 458 |
| 16 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |

## Long Stop-Window Overlap
| Stop | Case | Memory | Steps Completed | Memory Requests | Same Stack | Same Controller | Same Class |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2us | full_3d_snn_window | hbm_like | 1 | 234 | False | False | False |
| 2us | full_3d_snn_window_monolithic_proxy | monolithic_like | 28 | 416 | False | False | False |
| 2us | full_3d_snn_window_bundle_v3 | hbm_like | 1 | 912 | False | False | False |
| 10us | full_3d_snn_window | hbm_like | 25 | 416 | False | False | False |
| 10us | full_3d_snn_window_monolithic_proxy | monolithic_like | 250 | 416 | False | False | False |
| 10us | full_3d_snn_window_bundle_v3 | hbm_like | 89 | 1020 | True | True | True |
| 20us | full_3d_snn_window | hbm_like | 303 | 416 | False | False | False |
| 20us | full_3d_snn_window_monolithic_proxy | monolithic_like | 528 | 416 | False | False | False |
| 20us | full_3d_snn_window_bundle_v3 | hbm_like | 367 | 1020 | True | True | True |

### Stop-Window Compare
| Stop | Compare | Memory Delta | Steps Delta | Same Stack Delta | Same Controller Delta | Same Class Delta |
| --- | --- | --- | --- | --- | --- | --- |
| 2us | window_stop_bundle_vs_direct | 678 | 0 | 0 | 0 | 0 |
| 2us | window_stop_monolithic_vs_direct | 182 | 27 | 0 | 0 | 0 |
| 10us | window_stop_bundle_vs_direct | 604 | 64 | 1 | 1 | 1 |
| 10us | window_stop_monolithic_vs_direct | 0 | 225 | 0 | 0 | 0 |
| 20us | window_stop_bundle_vs_direct | 604 | 64 | 1 | 1 | 1 |
| 20us | window_stop_monolithic_vs_direct | 0 | 225 | 0 | 0 | 0 |

## HotSpot Runtime Signals
_None_
