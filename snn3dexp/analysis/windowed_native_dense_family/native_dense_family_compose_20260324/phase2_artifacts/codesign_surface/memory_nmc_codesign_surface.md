# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_compose_20260324/window_ablation/native_dense_fixed_step_4_10us.json`
- baseline_run_tag: `native_dense_fixed_step_4_10us`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_compose_20260324/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: ``
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/windowed_native_dense_family/native_dense_family_compose_20260324/phase2_artifacts/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d_snn_window | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_bundle_v3 | hbm_like | 0 | 0 | 0 | 0 | 0 |  | 0.094 | 0.000 | 0.000 |
| full_3d_snn_window_monolithic_proxy | monolithic_like | 0 | 0 | 0 | 0 | 0 |  | 0.500 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 | 0 | 0.000 | 0 | -0.094 | 0.129 |

## Traffic-Mem Mechanism Decomposition
| Compare | Mechanism Group | Metric | Delta | Amplification |
| --- | --- | --- | --- | --- |
| traffic_mem_monolithic_vs_hbm | memory_requests | memory_requests_total | 0 | NA |
| traffic_mem_monolithic_vs_hbm | service | total_service_deficit | 0 | NA |
| traffic_mem_monolithic_vs_hbm | topology | vertical_hops_ratio | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | routing_locality | remote_home_ratio | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | home_semantics | tier_local_home_access_ratio | 0.000 | 1.000 |
| traffic_mem_monolithic_vs_hbm | home_semantics | same_xy_cross_tier_access_ratio | -0.406 | 0.381 |
| traffic_mem_monolithic_vs_hbm | home_semantics | remote_home_access_ratio | 0.406 | 5.333 |
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
| traffic_mem_monolithic_vs_hbm | thermal | vertical_link_pressure | -0.094 | 0.615 |
| traffic_mem_monolithic_vs_hbm | reliability | reliability_penalty | 0.129 | 1.295 |
| traffic_mem_monolithic_vs_hbm | runtime | memory_requests_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | total_service_deficit_per_completed_step | 0.000 | NA |
| traffic_mem_monolithic_vs_hbm | runtime | stall_on_step_gate_cycles_per_completed_step | 0.000 | NA |

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 0 | 0.000 | 0.000 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 0 | 0.000 | 0.000 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 0 | 0.000 | 0.000 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 0 | NA | 0 | 0 |

### Window Monolithic vs HBM
| Steps | Spike Budget | Memory Delta | Stall / Step Delta | Gather Delta | Stream Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 0 | 0.000 | 0 | 0 |

### Window Spike Sensitivity
_None_

## Long Stop-Window Overlap
_None_

### Stop-Window Compare
_None_

## HotSpot Runtime Signals
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (3 cases)
_None_
