# Controller Explainability Loss Report

- Surfaces: controller_runtime_refresh_20260322, codesign_single_20us_20260322, perf_20us

## Surface Cases
| Surface | Case | Signal | Explainability | Controller Explainable | Active Ctrls | Runtime Ctrl | Runtime Mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | full_3d | runtime_controller | runtime_controller | True | 16 | 4 | traffic_semantic |
| controller_runtime_refresh_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 0 | traffic_semantic |
| controller_runtime_refresh_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | True | 16 | 4 | traffic_semantic |
| codesign_single_20us_20260322 | baseline_2d | synthetic_or_unknown | synthetic_or_unknown | False | 0 | -1 |  |
| codesign_single_20us_20260322 | memory_only_3d | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | noc_only_3d | synthetic_or_unknown | synthetic_or_unknown | False | 0 | -1 | generic_processing |
| codesign_single_20us_20260322 | full_3d | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_monolithic_proxy | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_mapping | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_thermal_guard | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_runtime_adaptive | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | home_pressure | home_pressure_only | False | 0 | -1 | traffic_semantic |
| codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | synthetic_or_unknown | False | 0 | -1 | generic_processing |
| perf_20us | full_3d | home_pressure | home_pressure_only | False | 0 | -1 |  |
| perf_20us | full_3d_monolithic_proxy | home_pressure | home_pressure_only | False | 0 | -1 |  |
| perf_20us | full_3d_tile_bundle_v3 | home_pressure | home_pressure_only | False | 0 | -1 |  |

## Case Transitions
| Reference | Compare | Case | Explainability From | Explainability To | Transition | Loss Reasons |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | runtime_controller | home_pressure_only | controller_explainability_lost | 5 |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | home_pressure_only | controller_explainability_lost | 5 |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | home_pressure_only | controller_explainability_lost | 5 |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | runtime_controller | home_pressure_only | controller_explainability_lost | 6 |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | runtime_controller | home_pressure_only | controller_explainability_lost | 6 |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | runtime_controller | home_pressure_only | controller_explainability_lost | 6 |

## Explainability Loss
| Reference | Compare | Case | From | To | Loss Reasons | Preserved Traffic |
| --- | --- | --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing,runtime_mode_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing,runtime_mode_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | runtime_controller | home_pressure_only | controller_proxy_missing,controller_runtime_summary_missing,runtime_alignment_lost,controller_identity_missing,dominant_home_controller_ids_missing,runtime_mode_missing | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |

## Reason Rows
| Reference | Compare | Case | Family | Reason |
| --- | --- | --- | --- | --- |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_monolithic_proxy | preserved_real_traffic | home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | preserved_real_traffic | home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | loss_reason | runtime_mode_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d | preserved_real_traffic | home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | loss_reason | runtime_mode_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_monolithic_proxy | preserved_real_traffic | home_access_pressure_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | controller_proxy_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | controller_runtime_summary_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | runtime_alignment_lost |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | controller_identity_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | dominant_home_controller_ids_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | loss_reason | runtime_mode_missing |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | preserved_real_traffic | real_synapse_sources_present |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | preserved_real_traffic | semantic_addressing_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | preserved_real_traffic | traffic_runtime_enabled |
| controller_runtime_refresh_20260322 | perf_20us | full_3d_tile_bundle_v3 | preserved_real_traffic | home_access_pressure_enabled |
