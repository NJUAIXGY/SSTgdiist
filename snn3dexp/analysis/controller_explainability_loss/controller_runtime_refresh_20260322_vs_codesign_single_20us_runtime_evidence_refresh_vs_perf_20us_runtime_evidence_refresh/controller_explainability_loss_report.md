# Controller Explainability Loss Report

- Surfaces: controller_runtime_refresh_20260322, codesign_single_20us_20260322, perf_20us_route_refresh_v2

## Surface Cases
| Surface | Case | Signal | Explainability | Controller Explainable | Active Ctrls | Runtime Ctrl | Runtime Mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | full_3d | runtime_controller | runtime_controller | True | 16 | 4 | traffic_semantic |
| controller_runtime_refresh_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 0 | traffic_semantic |
| controller_runtime_refresh_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 4 | traffic_semantic |
| codesign_single_20us_20260322 | baseline_2d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| codesign_single_20us_20260322 | memory_only_3d | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | noc_only_3d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| codesign_single_20us_20260322 | full_3d | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 0 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_mapping | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_thermal_guard | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_runtime_adaptive | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| codesign_single_20us_20260322 | full_3d_snn_window | runtime_controller | runtime_controller | True | 16 | 12 | mixed |
| codesign_single_20us_20260322 | full_3d_snn_window_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 0 | mixed |
| codesign_single_20us_20260322 | full_3d_snn_window_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 6 | mixed |
| perf_20us_route_refresh_v2 | baseline_2d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| perf_20us_route_refresh_v2 | memory_only_3d | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| perf_20us_route_refresh_v2 | noc_only_3d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| perf_20us_route_refresh_v2 | full_3d | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| perf_20us_route_refresh_v2 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 0 | traffic_semantic |
| perf_20us_route_refresh_v2 | full_3d_mapping | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| perf_20us_route_refresh_v2 | full_3d_thermal_guard | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| perf_20us_route_refresh_v2 | full_3d_runtime_adaptive | runtime_controller | runtime_controller | True | 16 | 8 | traffic_semantic |
| perf_20us_route_refresh_v2 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 4 | traffic_semantic |
| perf_20us_route_refresh_v2 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| perf_20us_route_refresh_v2 | full_3d_snn_window | runtime_controller | runtime_controller | True | 16 | 12 | mixed |
| perf_20us_route_refresh_v2 | full_3d_snn_window_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 0 | mixed |
| perf_20us_route_refresh_v2 | full_3d_snn_window_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 6 | mixed |

## Case Transitions
| Reference | Compare | Case | Explainability From | Explainability To | Transition | Loss Reasons |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | runtime_controller | runtime_controller | stable | 0 |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | stable | 0 |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | stable | 0 |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d | runtime_controller | runtime_controller | stable | 0 |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | stable | 0 |
| controller_runtime_refresh_20260322 | perf_20us_route_refresh_v2 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | stable | 0 |

## Explainability Loss
_None_

## Reason Rows
_None_
