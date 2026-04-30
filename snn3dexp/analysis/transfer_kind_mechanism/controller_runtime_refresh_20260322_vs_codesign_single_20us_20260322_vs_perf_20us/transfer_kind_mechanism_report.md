# Transfer-Kind Mechanism Report

## Sources
- surface_summaries: `/home/xgy/remote/snn3dexp/analysis/codesign_surface/controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322_same_tag_real_home_flow/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/codesign_surface/perf_20us_route_nmc_compare_real_home_flow/memory_nmc_codesign_surface_summary.json`

## Surface Cases
| Surface | Case | Signal | Transfer Kind | Runtime Align | Memory Requests | Service Deficit |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | full_3d | runtime_controller | runtime_class_unresolved | True | 3068 | 1537 |
| controller_runtime_refresh_20260322 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 6144 | 0 |
| controller_runtime_refresh_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 3268 | 6812 |
| codesign_single_20us_20260322 | baseline_2d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| codesign_single_20us_20260322 | memory_only_3d | home_pressure | unevaluable | False | 58560 | 90726 |
| codesign_single_20us_20260322 | noc_only_3d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| codesign_single_20us_20260322 | full_3d | home_pressure | unevaluable | False | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_monolithic_proxy | home_pressure | unevaluable | False | 159744 | 40128 |
| codesign_single_20us_20260322 | full_3d_mapping | home_pressure | unevaluable | False | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_thermal_guard | home_pressure | unevaluable | False | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_runtime_adaptive | home_pressure | unevaluable | False | 58560 | 90726 |
| codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | home_pressure | unevaluable | False | 58560 | 298248 |
| codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| perf_20us | full_3d | home_pressure | unevaluable | False | 58560 | 90726 |
| perf_20us | full_3d_monolithic_proxy | home_pressure | unevaluable | False | 159744 | 40128 |
| perf_20us | full_3d_tile_bundle_v3 | home_pressure | unevaluable | False | 58560 | 298248 |

## Cross-Surface Transitions
| From | To | Case | Signal From | Signal To | Signal Drop | Transfer From | Transfer To | Transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | runtime_controller | home_pressure | 2 | runtime_class_unresolved | unevaluable | signal_degraded |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | home_pressure | 2 | cross_class_transfer | unevaluable | signal_degraded |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | home_pressure | 2 | runtime_class_unresolved | unevaluable | signal_degraded |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | runtime_controller | home_pressure | 2 | runtime_class_unresolved | unevaluable | signal_degraded |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | runtime_controller | home_pressure | 2 | cross_class_transfer | unevaluable | signal_degraded |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | runtime_controller | home_pressure | 2 | runtime_class_unresolved | unevaluable | signal_degraded |

## Intra-Surface Compare
| Surface | Compare | Base | Compare Case | Memory Delta | Deficit Delta | Base Transfer | Compare Transfer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 200 | 5275 | runtime_class_unresolved | runtime_class_unresolved |
| controller_runtime_refresh_20260322 | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 3076 | -1537 | runtime_class_unresolved | cross_class_transfer |
| codesign_single_20us_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | unevaluable | unevaluable |
| codesign_single_20us_20260322 | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 101184 | -50598 | unevaluable | unevaluable |
| perf_20us | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | unevaluable | unevaluable |
| perf_20us | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 101184 | -50598 | unevaluable | unevaluable |

## Bundle Convergence
| Surface | Rows | Earliest Aligned Stop | Initial Transfer | Final Transfer | Max Controller Overlap Delta | Converged |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 3 | 10us | runtime_class_unresolved | aligned_same_controller | 1 | True |
| codesign_single_20us_20260322 | 0 |  |  |  | 0 | False |
| perf_20us | 0 |  |  |  | 0 | False |

## Window Progression
| Surface | Stop | Compare Transfer | Controller Overlap Delta | Memory Delta | Steps Delta |
| --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| controller_runtime_refresh_20260322 | 10us | aligned_same_controller | 1 | 604 | 64 |
| controller_runtime_refresh_20260322 | 20us | aligned_same_controller | 1 | 604 | 64 |
