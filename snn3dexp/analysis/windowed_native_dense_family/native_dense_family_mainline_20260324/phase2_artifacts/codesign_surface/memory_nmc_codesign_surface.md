# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_mainline_20260324/window_ablation/native_dense_fixed_step_8_20us.json`
- baseline_run_tag: `native_dense_fixed_step_8_20us`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_mainline_20260324/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: ``
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_mainline_20260324/phase2_artifacts/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d_snn_window | hbm_like | 448 | 64 | 128 | 64 | 0 | tier_local_home | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 500 | 348 | 144 | 0 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 64 | 128 | 64 | 0 | tier_local_home | 0.500 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 | 96 | 0.000 | 0 | -0.294 | 0.080 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
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
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | 0.080 | 1.127 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | -14186.125 | 0.101 |

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 448 | 149.333 | 30888.333 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 112.000 | 2368.000 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 1256 | 628.000 | 44465.000 |
| 8 | full_3d_snn_window | hbm_like | 448 | 56.000 | 15786.125 |
| 8 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 56.000 | 1600.000 |
| 8 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 185.500 | 25388.750 |
| 16 | full_3d_snn_window | hbm_like | 448 | 28.000 | 7925.062 |
| 16 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 28.000 | 832.000 |
| 16 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 92.750 | 12726.375 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 808 | 2.804 | 256 | 73 |
| 4 | sp64 | 1312 | 3.929 | 1497 | 428 |
| 8 | default | 1036 | 3.312 | 268 | 76 |
| 8 | sp64 | 1344 | 4.000 | 1512 | 432 |
| 16 | default | 1036 | 3.312 | 268 | 76 |
| 16 | sp64 | 1344 | 4.000 | 1512 | 432 |

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
| 8 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 8 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 16 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |

## Long Stop-Window Overlap
_None_

### Stop-Window Compare
_None_

## HotSpot Runtime Signals
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (3 cases)
_None_
