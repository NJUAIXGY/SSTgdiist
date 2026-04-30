# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/windowed_controller_runtime_refresh_20260322_ablation.json`
- baseline_run_tag: `controller_runtime_refresh_20260322`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/paper_artifacts/controller_runtime_refresh_20260322_windowed_snapshot/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d_snn_window | hbm_like | 234 | 64 | 64 | 24 | 0 | tier_local_home | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_bundle_v3 | hbm_like | 912 | 276 | 256 | 96 | 8 | tier_local_home | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_monolithic_proxy | monolithic_like | 416 | 64 | 128 | 48 | 0 | tier_local_home | 0.500 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 182 | 0 | 96 | 0.000 | 0 | -0.292 | -0.036 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
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

## HotSpot Runtime Signals
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (3 cases)
_None_
