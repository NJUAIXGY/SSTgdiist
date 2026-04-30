# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/ablation_summary_balanced_20us_refresh_20260322_015217.json`
- baseline_run_tag: `balanced_20us`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: `/home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_2us_ablation.json, /home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_10us_ablation.json, /home/xgy/remote/snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/window_stop_20us_ablation.json`
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/paper_artifacts/balanced_20us/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_2d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| memory_only_3d | hbm_like | 39936 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| noc_only_3d | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d | hbm_like | 39936 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d_monolithic_proxy | monolithic_like | 1752 | 512 | 512 | 256 | 656 | same_xy_cross_tier | 0.500 | 0.000 | 0.000 |
| full_3d_mapping | hbm_like | 448 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d_thermal_guard | hbm_like | 448 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |
| full_3d_runtime_adaptive | hbm_like | 448 | 0 | 0 | 0 | 0 |  | 0.094 | 0.000 | 0.000 |
| full_3d_tile_bundle_v3 | hbm_like | 440 | 1422 | 1422 | 711 | 4046 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| noc_only_3d_bundle_fault_v3 | legacy_per_pe | 0 | 0 | 0 | 0 | 0 |  | 0.000 | 0.000 | 0.000 |

## Traffic-Mem Compare
| Compare | Base | Compare Case | Memory Delta | Service Deficit Delta | Remote-Home Demand Delta | Active Stack Util Delta | Hot Stack Deficit Delta | Vertical Link Delta | Reliability Delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | -39496 | 4046 | 0 | 0.000 | 0 | NA | NA |
| traffic_mem_monolithic_vs_hbm | full_3d | full_3d_monolithic_proxy | -38184 | 656 | 0 | 0.000 | 0 | 0.150 | 0.489 |

## Traffic-Mem Mechanism Decomposition
_None_

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
Threshold profile: 70.0C via `default_hotspot_threshold_c` (10 cases)
| Compare | Vertical Link Delta | Hotspot Penalty Delta | Home-Route Adjustment Delta |
| --- | --- | --- | --- |
| runtime_adaptive_vs_mapping | 0.000 | 0.232 | 2.000 |
| runtime_adaptive_vs_thermal_guard | 0.094 | 0.232 | 2.000 |
