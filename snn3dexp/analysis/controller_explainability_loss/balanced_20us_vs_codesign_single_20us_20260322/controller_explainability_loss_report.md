# Controller Explainability Loss Report

- Surfaces: balanced_20us, codesign_single_20us_20260322

## Surface Cases
| Surface | Case | Signal | Explainability | Controller Explainable | Active Ctrls | Runtime Ctrl | Runtime Mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | baseline_2d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| balanced_20us | memory_only_3d | synthetic_or_unknown | controller_proxy_only | False | 16 | 1 | generic_processing |
| balanced_20us | noc_only_3d | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
| balanced_20us | full_3d | synthetic_or_unknown | controller_proxy_only | False | 16 | 1 | generic_processing |
| balanced_20us | full_3d_monolithic_proxy | runtime_controller | runtime_controller | True | 16 | 0 | traffic_semantic |
| balanced_20us | full_3d_mapping | real_synapse_only | controller_proxy_only | False | 8 | 0 | generic_processing |
| balanced_20us | full_3d_thermal_guard | real_synapse_only | controller_proxy_only | False | 8 | 0 | generic_processing |
| balanced_20us | full_3d_runtime_adaptive | real_synapse_only | controller_proxy_only | False | 8 | 0 | generic_processing |
| balanced_20us | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | True | 4 | 0 | traffic_semantic |
| balanced_20us | noc_only_3d_bundle_fault_v3 | synthetic_or_unknown | controller_proxy_only | False | 0 | -1 | generic_processing |
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

## Case Transitions
| Reference | Compare | Case | Explainability From | Explainability To | Transition | Loss Reasons |
| --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | codesign_single_20us_20260322 | baseline_2d | controller_proxy_only | controller_proxy_only | stable | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d | controller_proxy_only | runtime_controller | controller_explainability_gained | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | controller_proxy_only | runtime_controller | controller_explainability_gained | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d_monolithic_proxy | runtime_controller | runtime_controller | stable | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | controller_proxy_only | runtime_controller | controller_explainability_gained | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | controller_proxy_only | runtime_controller | controller_explainability_gained | 0 |
| balanced_20us | codesign_single_20us_20260322 | full_3d_tile_bundle_v3 | runtime_controller | runtime_controller | stable | 0 |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | controller_proxy_only | runtime_controller | controller_explainability_gained | 0 |
| balanced_20us | codesign_single_20us_20260322 | noc_only_3d | controller_proxy_only | controller_proxy_only | stable | 0 |
| balanced_20us | codesign_single_20us_20260322 | noc_only_3d_bundle_fault_v3 | controller_proxy_only | controller_proxy_only | stable | 0 |

## Explainability Loss
| Reference | Compare | Case | From | To | Loss Reasons | Preserved Traffic |
| --- | --- | --- | --- | --- | --- | --- |
| balanced_20us | codesign_single_20us_20260322 | full_3d | controller_proxy_only | runtime_controller |  | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | controller_proxy_only | runtime_controller |  | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | controller_proxy_only | runtime_controller |  | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | controller_proxy_only | runtime_controller |  | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | controller_proxy_only | runtime_controller |  | real_synapse_sources_present,semantic_addressing_enabled,traffic_runtime_enabled,home_access_pressure_enabled |

## Reason Rows
| Reference | Compare | Case | Family | Reason |
| --- | --- | --- | --- | --- |
| balanced_20us | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | real_synapse_sources_present |
| balanced_20us | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | semantic_addressing_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | traffic_runtime_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d | preserved_real_traffic | home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | preserved_real_traffic | real_synapse_sources_present |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | preserved_real_traffic | semantic_addressing_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | preserved_real_traffic | traffic_runtime_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_mapping | preserved_real_traffic | home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | preserved_real_traffic | real_synapse_sources_present |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | preserved_real_traffic | semantic_addressing_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | preserved_real_traffic | traffic_runtime_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_runtime_adaptive | preserved_real_traffic | home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | preserved_real_traffic | real_synapse_sources_present |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | preserved_real_traffic | semantic_addressing_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | preserved_real_traffic | traffic_runtime_enabled |
| balanced_20us | codesign_single_20us_20260322 | full_3d_thermal_guard | preserved_real_traffic | home_access_pressure_enabled |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | preserved_real_traffic | real_synapse_sources_present |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | preserved_real_traffic | semantic_addressing_enabled |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | preserved_real_traffic | traffic_runtime_enabled |
| balanced_20us | codesign_single_20us_20260322 | memory_only_3d | preserved_real_traffic | home_access_pressure_enabled |
