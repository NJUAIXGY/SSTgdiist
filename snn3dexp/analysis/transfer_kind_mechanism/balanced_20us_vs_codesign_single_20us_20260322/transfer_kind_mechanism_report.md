# Transfer-Kind Mechanism Report

## Sources
- surface_summaries: `/home/xgy/remote/snn3dexp/analysis/paper_artifacts/balanced_20us/codesign_surface/memory_nmc_codesign_surface_summary.json, /home/xgy/remote/snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322/codesign_surface/memory_nmc_codesign_surface_summary.json`

## Surface Cases
| Surface | Case | Signal | Transfer Kind | Runtime Align | Memory Requests | Service Deficit |
| --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | baseline_2d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| balanced_20us | memory_only_3d | synthetic_or_unknown | runtime_class_unresolved | True | 39936 | 0 |
| balanced_20us | noc_only_3d | synthetic_or_unknown | unevaluable | False | 0 | 0 |
| balanced_20us | full_3d | synthetic_or_unknown | runtime_class_unresolved | True | 39936 | 0 |
| balanced_20us | full_3d_monolithic_proxy | runtime_controller | cross_class_transfer | True | 1752 | 656 |
| balanced_20us | full_3d_mapping | real_synapse_only | cross_class_transfer | True | 448 | 0 |
| balanced_20us | full_3d_thermal_guard | real_synapse_only | cross_class_transfer | True | 448 | 0 |
| balanced_20us | full_3d_runtime_adaptive | real_synapse_only | cross_class_transfer | True | 448 | 0 |
| balanced_20us | full_3d_tile_bundle_v3 | runtime_controller | cross_class_transfer | True | 440 | 4046 |
| balanced_20us | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | unevaluable | False | 0 | 0 |
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

## Cross-Surface Transitions
| From | To | Case | Signal From | Signal To | Signal Drop | Transfer From | Transfer To | Transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | codesign_single_20us_20260322 | baseline_2d | synthetic_or_unknown | synthetic_or_unknown | 0 | unevaluable | unevaluable | stable |
| balanced_20us | codesign_single_20us_20260322 | full_3d | synthetic_or_unknown | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | signal_elevated |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | real_synapse_only | runtime_controller | 0 | cross_class_transfer | runtime_class_unresolved | signal_elevated |
| balanced_20us | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | 0 | cross_class_transfer | cross_class_transfer | stable |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | real_synapse_only | runtime_controller | 0 | cross_class_transfer | runtime_class_unresolved | signal_elevated |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | real_synapse_only | runtime_controller | 0 | cross_class_transfer | runtime_class_unresolved | signal_elevated |
| balanced_20us | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | 0 | cross_class_transfer | runtime_class_unresolved | transfer_changed |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | synthetic_or_unknown | runtime_controller | 0 | runtime_class_unresolved | runtime_class_unresolved | signal_elevated |
| balanced_20us | codesign_single_20us_20260322 | noc_only_3d | synthetic_or_unknown | synthetic_or_unknown | 0 | unevaluable | unevaluable | stable |
| balanced_20us | codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | synthetic_or_unknown | 0 | unevaluable | unevaluable | stable |

## Intra-Surface Compare
| Surface | Compare | Base | Compare Case | Memory Delta | Deficit Delta | Base Transfer | Compare Transfer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | -39496 | 4046 | runtime_class_unresolved | cross_class_transfer |
| balanced_20us | traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | -38184 | 656 | runtime_class_unresolved | cross_class_transfer |
| codesign_single_20us_20260322 | traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 207522 | runtime_class_unresolved | runtime_class_unresolved |
| codesign_single_20us_20260322 | traffic_mem_monolithic_vs_hbm | full_3d_snn_window | full_3d_snn_window_monolithic_proxy | 0 | 0 |  |  |

## Bundle Convergence
| Surface | Rows | Earliest Aligned Stop | Initial Transfer | Final Transfer | Max Controller Overlap Delta | Converged |
| --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | 3 | 10us | runtime_class_unresolved | aligned_same_controller | 1 | True |
| codesign_single_20us_20260322 | 3 | 10us | runtime_class_unresolved | aligned_same_controller | 1 | True |

## Window Progression
| Surface | Stop | Compare Transfer | Controller Overlap Delta | Memory Delta | Steps Delta |
| --- | --- | --- | --- | --- | --- |
| balanced_20us | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| balanced_20us | 10us | aligned_same_controller | 1 | 604 | 64 |
| balanced_20us | 20us | aligned_same_controller | 1 | 604 | 64 |
| codesign_single_20us_20260322 | 2us | runtime_class_unresolved | 0 | 678 | 0 |
| codesign_single_20us_20260322 | 10us | aligned_same_controller | 1 | 604 | 64 |
| codesign_single_20us_20260322 | 20us | aligned_same_controller | 1 | 604 | 64 |
