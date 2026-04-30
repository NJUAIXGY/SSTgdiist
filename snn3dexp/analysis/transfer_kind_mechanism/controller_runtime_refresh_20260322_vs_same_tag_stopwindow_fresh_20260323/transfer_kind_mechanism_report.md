# Transfer-Kind Mechanism Report

## Sources
- surface_summaries: `/home/xgy/remote/snn3dexp/analysis/paper_artifacts/controller_runtime_refresh_20260322_windowed_snapshot_default_refresh/codesign_surface/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323/memory_nmc_codesign_surface_summary.json`

## Surface Cases
| Surface | Case | Signal | Transfer Kind | Runtime Align | Memory Requests | Service Deficit |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | full_3d | runtime_controller | runtime_class_unresolved | True | 3068 | 1537 |
| controller_runtime_refresh_20260322 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 6144 | 0 |
| controller_runtime_refresh_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 3268 | 6812 |
| same_tag_stopwindow_fresh_20260323 | baseline_2d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| same_tag_stopwindow_fresh_20260323 | memory_only_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| same_tag_stopwindow_fresh_20260323 | noc_only_3d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| same_tag_stopwindow_fresh_20260323 | full_3d | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| same_tag_stopwindow_fresh_20260323 | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 159744 | 40128 |
| same_tag_stopwindow_fresh_20260323 | full_3d_mapping | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| same_tag_stopwindow_fresh_20260323 | full_3d_thermal_guard | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| same_tag_stopwindow_fresh_20260323 | full_3d_runtime_adaptive | runtime_controller | runtime_class_unresolved | True | 58560 | 90726 |
| same_tag_stopwindow_fresh_20260323 | full_3d_tile_bundle_v3 | runtime_controller | runtime_class_unresolved | True | 58560 | 298248 |
| same_tag_stopwindow_fresh_20260323 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | unevaluable | False | 0 | 0 |

## Cross-Surface Transitions
| From | To | Case | Signal From | Signal To | Signal Drop | Transfer From | Transfer To | Transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | same_tag_stopwindow_fresh_20260323 | full_3d | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |
| controller_runtime_refresh_20260322 | same_tag_stopwindow_fresh_20260323 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | 0 | cross_class_transfer | cross_class_transfer | stable |
| controller_runtime_refresh_20260322 | same_tag_stopwindow_fresh_20260323 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | stable |

## Intra-Surface Compare
| Surface | Compare | Base | Compare Case | Memory Delta | Deficit Delta | Base Transfer | Compare Transfer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 200 | 5275 | runtime_class_unresolved | runtime_class_unresolved |
| controller_runtime_refresh_20260322 | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | 3076 | -1537 | runtime_class_unresolved | cross_class_transfer |
| same_tag_stopwindow_fresh_20260323 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | runtime_class_unresolved | runtime_class_unresolved |
| same_tag_stopwindow_fresh_20260323 | traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 |  |  |

## Bundle Convergence
| Surface | Rows | Earliest Aligned Stop | Initial Transfer | Final Transfer | Max Controller Overlap Delta | Converged |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 1 |  | runtime_class_unresolved | runtime_class_unresolved | 0 | False |
| same_tag_stopwindow_fresh_20260323 | 3 | 10us | runtime_class_unresolved | aligned_same_controller | 1 | True |

## Window Progression
| Surface | Stop | Compare Transfer | Controller Overlap Delta | Memory Delta | Steps Delta |
| --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| same_tag_stopwindow_fresh_20260323 | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| same_tag_stopwindow_fresh_20260323 | 10us | aligned_same_controller | 1 | 604 | 64 |
| same_tag_stopwindow_fresh_20260323 | 20us | aligned_same_controller | 1 | 604 | 64 |
