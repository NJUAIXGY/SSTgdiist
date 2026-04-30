# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/traffic_baseline_ablation.json`
- baseline_run_tag: `archsum_matrix_smoke`
- baseline_overlay_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/runtime_canonical_ablation.json`
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/window_stop_analysis/window_stop_2us_ablation.json, /home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/window_stop_analysis/window_stop_5us_ablation.json, /home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/window_stop_analysis/window_stop_10us_ablation.json`
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/phase2_artifacts/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_2d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| memory_only_3d | hbm_like | 6144 | 1024 | 1024 | 512 | 0 | remote_home | 0.500 | 0.000 | 0.000 |
| noc_only_3d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d | hbm_like | 6144 | 1024 | 1024 | 512 | 0 | remote_home | 0.500 | 0.000 | 0.000 |
| full_3d_monolithic_proxy | monolithic_like | 6144 | 1024 | 1024 | 512 | 0 | same_xy_cross_tier | 0.500 | 0.000 | 0.000 |
| full_3d_runtime_adaptive | hbm_like | 912 | 276 | 256 | 96 | 8 | tier_local_home | 0.094 | 0.000 | 0.000 |
| full_3d_tile_bundle_v3 | hbm_like | 16884 | 2814 | 2814 | 1407 | 0 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 10740 | 0 | -498 | 0.000 | 0 | NA | NA |
| traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 0 | 0 | -832 | 0.000 | 0 | -0.050 | 0.074 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | route_packetization | router_bundle_v3_rx_total | 1440 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_bundle_v3_packets_total | 512 | NA |
| traffic_mem_bundle_vs_direct | route_packetization | tx_spikekey_v4_packets_total | -896 | 0.000 |
| traffic_mem_bundle_vs_direct | processing_writeback | gas_scatter_spikes_emitted_total | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_demands | 895 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_metadata | metadata_lookup_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_demands | 1790 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_synapse | synapse_gather_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_demands | 1790 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_stream | stream_region_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_demands | 895 | 2.748 |
| traffic_mem_bundle_vs_direct | memory_writeback | writeback_region_backlog | 0 | NA |
| traffic_mem_bundle_vs_direct | home_access_class | tier_local_home_total_demands | 916 | 2.789 |
| traffic_mem_bundle_vs_direct | home_access_class | same_xy_cross_tier_total_demands | 3162 | 7.176 |
| traffic_mem_bundle_vs_direct | home_access_class | remote_home_total_demands | -498 | 0.514 |
| traffic_mem_bundle_vs_direct | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_bundle_vs_direct | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_memory_request_skew | 0.029 | 1.029 |
| traffic_mem_bundle_vs_direct | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_bundle_vs_direct | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 0 | 1.000 |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | -0.500 | 0.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | tier_local_home_total_demands | 0 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_access_class | same_xy_cross_tier_total_demands | 832 | 2.625 |
| traffic_mem_monolithic_vs_hbm | home_access_class | remote_home_total_demands | -832 | 0.188 |
| traffic_mem_monolithic_vs_hbm | home_pressure | tier_local_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | same_xy_cross_tier_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | remote_home_service_deficit_attribution | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_pressure | attributed_service_deficit_total | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | active_stack_utilization | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_stack_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | most_pressured_controller_service_deficit_proxy | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_memory_request_skew | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | stack_pressure | stack_service_deficit_skew | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | -0.050 | 0.750 |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | 0.074 | 1.178 |
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

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 808 | 2.804 | 256 | 73 |

### Window Gating vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Activation Delta | Gating Activation Delta | Unique Source Delta |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | default | -448 | 0.000 | 16 | 256 | 8 |

### Window Monolithic vs HBM
| Steps | Spike Budget | Memory Delta | Stall / Step Delta | Gather Delta | Stream Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 0 | -28520.333 | 0 | 0 |

### Window Spike Sensitivity
_None_

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
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (7 cases)
| Compare | Vertical Link Delta | Hotspot Penalty Delta | Home-Route Adjustment Delta |
| --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | 0.238 | 0.132 | 1.000 |
