# Transfer-Kind Mechanism Report

## Sources
- surface_summaries: `/home/xgy/remote/snn3dexp/analysis/codesign_surface/controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322_runtime_evidence_refresh/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/codesign_surface/perf_20us_route_nmc_compare_runtime_evidence_refresh/memory_nmc_codesign_surface_summary.json`

## Surface Cases
| Surface | Case | Signal | Transfer Kind | Runtime Align | Memory Requests | Service Deficit |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | full_3d | runtime_controller | runtime_class_unresolved | True | 3068 | 1537 |
| controller_runtime_refresh_20260322 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 6144 | 0 |
| controller_runtime_refresh_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 3268 | 6812 |
| codesign_single_20us_20260322 | baseline_2d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| codesign_single_20us_20260322 | memory_only_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| codesign_single_20us_20260322 | noc_only_3d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| codesign_single_20us_20260322 | full_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 159744 | 40128 |
| codesign_single_20us_20260322 | full_3d_mapping | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_thermal_guard | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_runtime_adaptive | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 58560 | 298248 |
| codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| codesign_single_20us_20260322 | full_3d_snn_window | runtime_controller | cross_class_transfer | True | 416 | 0 |
| codesign_single_20us_20260322 | full_3d_snn_window_bundle_v3 | runtime_controller | aligned_same_controller | True | 1020 | 0 |
| codesign_single_20us_20260322 | full_3d_snn_window_monolithic_proxy | runtime_controller | cross_class_transfer | True | 416 | 0 |
| perf_20us_route_refresh_v2 | baseline_2d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| perf_20us_route_refresh_v2 | memory_only_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| perf_20us_route_refresh_v2 | noc_only_3d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| perf_20us_route_refresh_v2 | full_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| perf_20us_route_refresh_v2 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 6144 | 0 |
| perf_20us_route_refresh_v2 | full_3d_mapping | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| perf_20us_route_refresh_v2 | full_3d_thermal_guard | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| perf_20us_route_refresh_v2 | full_3d_runtime_adaptive | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| perf_20us_route_refresh_v2 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 3268 | 6812 |
| perf_20us_route_refresh_v2 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| perf_20us_route_refresh_v2 | full_3d_snn_window | runtime_controller | cross_class_transfer | True | 416 | 0 |
| perf_20us_route_refresh_v2 | full_3d_snn_window_bundle_v3 | runtime_controller | aligned_same_controller | True | 1020 | 0 |
| perf_20us_route_refresh_v2 | full_3d_snn_window_monolithic_proxy | runtime_controller | cross_class_transfer | True | 416 | 0 |

## Cross-Surface Transitions
| From | To | Case | Signal From | Signal To | Signal Drop | Transfer From | Transfer To | Transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | 0 | cross_class_transfer | cross_class_transfer | stable |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | 0 | cross_class_transfer | cross_class_transfer | stable |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |

## Intra-Surface Compare
| Surface | Compare | Base | Compare Case | Memory Delta | Deficit Delta | Base Transfer | Compare Transfer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 200 | 5275 | runtime_class_unresolved | runtime_class_unresolved |
| controller_runtime_refresh_20260322 | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 3076 | -1537 | runtime_class_unresolved | cross_class_transfer |
| codesign_single_20us_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | runtime_class_unresolved | runtime_class_unresolved |
| codesign_single_20us_20260322 | traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 | cross_class_transfer | cross_class_transfer |
| perf_20us_route_refresh_v2 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | -55292 | -83914 | runtime_class_unresolved | runtime_class_unresolved |
| perf_20us_route_refresh_v2 | traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 | cross_class_transfer | cross_class_transfer |

## Bundle Convergence
| Surface | Rows | Earliest Aligned Stop | Initial Transfer | Final Transfer | Max Controller Overlap Delta | Converged |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 3 | 10us | runtime_class_unresolved | aligned_same_controller | 1 | True |
| codesign_single_20us_20260322 | 0 |  |  |  | 0 | False |
| perf_20us_route_refresh_v2 | 0 |  |  |  | 0 | False |

## Window Progression
| Surface | Stop | Compare Transfer | Controller Overlap Delta | Memory Delta | Steps Delta |
| --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| controller_runtime_refresh_20260322 | 10us | aligned_same_controller | 1 | 604 | 64 |
| controller_runtime_refresh_20260322 | 20us | aligned_same_controller | 1 | 604 | 64 |
