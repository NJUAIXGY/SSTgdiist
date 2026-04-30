# Memory/NMC Co-Design Surface

## Sources
- baseline_ablation_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/runtime_canonical_ablation.json`
- baseline_run_tag: `archsum_matrix_smoke`
- baseline_overlay_ablation_paths: ``
- fixed_step_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/fixed_step_analysis/fixed_step_sweep_summary.json`
- stop_window_ablation_paths: ``
- hotspot_runtime_summary_path: `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/runtime_focus_phase2/phase2_runtime_summary.json`

## Traffic-Mem Baseline
| Case | Memory | Memory Requests | Gather Demands | Stream Demands | Writeback Demands | Service Deficit | Home Class | Remote-Home Share | Vertical Link Pressure | Reliability Penalty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d_mapping | hbm_like | 6144 | 1024 | 1024 | 512 | 0 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |
| full_3d_thermal_guard | hbm_like | 6144 | 1024 | 1024 | 512 | 0 | same_xy_cross_tier | 0.250 | 0.000 | 0.000 |
| full_3d_runtime_adaptive | hbm_like | 6144 | 1024 | 1024 | 512 | 0 | same_xy_cross_tier | 0.094 | 0.000 | 0.000 |

## Traffic-Mem Compare
_None_

## Traffic-Mem Mechanism Decomposition
_None_

## Windowed SNN Fixed-Step
| Steps | Case | Memory | Memory Requests | Memory / Step | Stall / Step |
| --- | --- | --- | --- | --- | --- |
| 4 | full_3d_snn_window | hbm_like | 448 | 149.333 | 30888.333 |
| 4 | full_3d_snn_window_bundle_v3 | hbm_like | 1256 | 628.000 | 44465.000 |
| 4 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 112.000 | 2368.000 |
| 4 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |
| 8 | full_3d_snn_window | hbm_like | 448 | 56.000 | 15786.125 |
| 8 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 185.500 | 25388.750 |
| 8 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 56.000 | 1600.000 |
| 8 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |
| 16 | full_3d_snn_window | hbm_like | 448 | 28.000 | 7925.062 |
| 16 | full_3d_snn_window_bundle_v3 | hbm_like | 1484 | 92.750 | 12726.375 |
| 16 | full_3d_snn_window_monolithic_proxy | monolithic_like | 448 | 28.000 | 832.000 |
| 16 | full_3d_snn_window_gating_event_synth | hbm_like | 0 | 0.000 | 64.000 |

### Window Bundle vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Router Bundle Rx Delta | Bundle Packet Delta |
| --- | --- | --- | --- | --- | --- |
| 4 | default | 808 | 2.804 | 256 | 73 |
| 4 | sp64 | 1312 | 3.929 | 1497 | 428 |
| 8 | default | 1036 | 3.312 | 268 | 76 |
| 8 | sp64 | 1344 | 4.000 | 1512 | 432 |
| 16 | default | 1036 | 3.312 | 268 | 76 |
| 16 | sp64 | 1344 | 4.000 | 1512 | 432 |

### Window Gating vs Direct
| Steps | Spike Budget | Memory Delta | Memory Amplification | Activation Delta | Gating Activation Delta | Unique Source Delta |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | default | -448 | 0.000 | 16 | 256 | 8 |
| 4 | sp64 | -448 | 0.000 | 64 | 448 | 8 |
| 8 | default | -448 | 0.000 | 16 | 256 | 8 |
| 8 | sp64 | -448 | 0.000 | 136 | 736 | 8 |
| 16 | default | -448 | 0.000 | 16 | 256 | 8 |
| 16 | sp64 | -448 | 0.000 | 280 | 1312 | 8 |

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
| 4 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 8 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 8 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_bundle_v3 | sp64 | 308 | 1244 | 356 |
| 16 | full_3d_snn_window_monolithic_proxy | sp64 | 0 | 0 | 0 |
| 16 | full_3d_snn_window_gating_event_synth | sp64 | 0 | 0 | 0 |

## Long Stop-Window Overlap
_None_

### Stop-Window Compare
_None_

## HotSpot Runtime Signals
Threshold profile: 70.0C via `effective_config.thermal.hotspot_threshold_c` (3 cases)
| Compare | Vertical Link Delta | Hotspot Penalty Delta | Home-Route Adjustment Delta |
| --- | --- | --- | --- |
| runtime_adaptive_vs_mapping | 0.000 | 0.000 | 2.000 |
| runtime_adaptive_vs_thermal_guard | 0.094 | 0.000 | 2.000 |
