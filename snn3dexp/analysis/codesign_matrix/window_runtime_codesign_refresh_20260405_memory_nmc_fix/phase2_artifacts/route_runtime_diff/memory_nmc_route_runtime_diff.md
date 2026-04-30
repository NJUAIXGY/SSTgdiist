# Memory/NMC Route Runtime Diff Report

- matrix_label: `window_runtime_codesign_refresh_20260405_memory_nmc_fix`

## Traffic Route Diffs

| compare_kind | base_case_id | compare_case_id | dominant_home_runtime_controller_overlap_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 845 | 465 |

## Window Route Diffs

| run_tag | base_case_id | compare_case_id | dataflow_controller_alignment_transition | pe_nic_dominant_controller_outstanding_requests_accum_delta | synapse_dominant_controller_outstanding_requests_accum_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | alignment_improved | -356163 | -355581 | 0 | 0 |

## Window Route Mechanism Focus

- row_count: `1`
- dominant_axis_counts: `{"controller_outstanding": 1}`
- alignment_transition_counts: `{"alignment_improved": 1}`
- stall_on_step_gate_cycles_per_completed_step_delta_sum: `13576.667`
- real_home_path_service_deficit_total_delta_sum: `0`
- controller_outstanding_delta_total_sum: `-711744`

| run_tag | stall_on_step_gate_cycles_per_completed_step_delta | memory_requests_per_completed_step_delta | controller_outstanding_delta_total | real_home_path_service_deficit_total_delta | dataflow_controller_alignment_transition | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | 13576.667 | 478.667 | -711744 | 0 | alignment_improved | controller_outstanding |

## Window Stop Progression

- row_count: `2`
- compare_kind_counts: `{"window_stop_bundle_vs_direct": 1, "window_stop_monolithic_vs_direct": 1}`
- dominant_axis_counts: `{"controller_outstanding": 2}`
- earliest_same_controller_overlap_stop_at: ``
- max_steps_completed_delta: `19`

| compare_kind | stop_at | steps_completed_delta | same_controller_overlap_delta | stall_on_step_gate_cycles_per_completed_step_delta | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- |
| window_stop_bundle_vs_direct | 2us | 0 | 0 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 2us | 19 | 0 | 0.000 | controller_outstanding |

## Runtime Compare Signals

- row_count: `1`
- compare_kind_counts: `{"runtime_adaptive_vs_full_3d": 1}`
- dominant_axis_counts: `{"memory_barrier_coupling_proxy": 1}`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- compare_route_memory_overlap_mode_counts: `{"native_synapse_aligned": 1}`
- route_memory_overlap_mode_transition_counts: `{"bootstrap_bound->native_synapse_aligned": 1}`
- compare_source_authority_tier_counts: `{"native_multicast_synapse_home": 1}`
- source_authority_tier_transition_counts: `{"bootstrap_manifest->native_multicast_synapse_home": 1}`
- compare_control_trigger_signal_counts: `{"memory_barrier_coupling_proxy": 1, "memory_thermal_coupling_proxy": 1, "route_memory_overlap": 1, "vertical_link_pressure": 1}`
- vertical_link_pressure_delta_sum: `0.201`
- route_thermal_coupling_score_delta_sum: `0.025`
- memory_thermal_coupling_proxy_delta_sum: `-22.633`
- memory_barrier_coupling_proxy_delta_sum: `69704.000`
- homeroute_adjustment_count_delta_sum: `2.000`

| compare_kind | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | source_authority_tier_transition | route_memory_overlap_mode_transition | vertical_link_pressure_delta | stack_hotspot_penalty_delta | route_thermal_coupling_score_delta | memory_thermal_coupling_proxy_delta | memory_barrier_coupling_proxy_delta | homeroute_adjustment_count_delta | thermal_guard_actions_delta | dominant_runtime_axis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | executed_control | hybrid | memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure | bootstrap_manifest->native_multicast_synapse_home | bootstrap_bound->native_synapse_aligned | 0.201 | 0.124 | 0.025 | -22.633 | 69704.000 | 2.000 | 2.000 | memory_barrier_coupling_proxy |

## Mechanism Progression

- progression_signature: `controller_outstanding -> controller_outstanding -> memory_barrier_coupling_proxy`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `controller_outstanding`
- runtime_compare_dominant_axis: `memory_barrier_coupling_proxy`
- runtime_compare_source_authority_tier: `native_multicast_synapse_home`
- source_authority_progression_signature: `window_route_unavailable -> window_stop_unavailable -> native_multicast_synapse_home`
- earliest_same_controller_overlap_stop_at: ``
- phase_transition_flags: `{"route_to_runtime_axis_shift": true, "route_to_stop_axis_shift": false, "same_controller_overlap_emerged": false, "stop_to_runtime_axis_shift": true}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window remains controller_outstanding, without same-controller overlap; runtime compare shifts to memory_barrier_coupling_proxy.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 1 | controller_outstanding | no | alignment={"alignment_improved": 1} |
| 2 | window_stop | 2 | controller_outstanding | no | same_controller_overlap@unavailable |
| 3 | runtime_compare | 1 | memory_barrier_coupling_proxy | yes | compare_kinds={"runtime_adaptive_vs_full_3d": 1} |

## Route/Memory Joint Pressure

- row_count: `2`
- compare_kind_counts: `{"traffic_mem_bundle_vs_direct": 1, "traffic_mem_monolithic_vs_hbm": 1}`
- dominant_endpoint_counts: `{"pe_nic": 2}`
- dominant_memory_axis_counts: `{"controller_service_deficit_proxy": 1, "controller_memory_pressure_proxy": 1}`
- dominant_backlog_region_counts: `{"stream_region": 1, "unavailable": 1}`
- compare_route_memory_overlap_mode_counts: `{"bootstrap_bound": 2}`
- compare_source_authority_tier_counts: `{"bootstrap_manifest": 2}`
- source_authority_tier_transition_counts: `{"bootstrap_manifest->bootstrap_manifest": 2}`
- base_memory_pressure_proxy_source_counts: `{"service_deficit": 2}`
- compare_memory_pressure_proxy_source_counts: `{"service_deficit": 1, "backpressure": 1}`
- memory_pressure_proxy_source_transition_counts: `{"service_deficit->service_deficit": 1, "service_deficit->backpressure": 1}`
- most_pressured_controller_backpressure_proxy_delta_sum: `-39.693`
- most_pressured_controller_memory_pressure_proxy_delta_sum: `243.440`
- top_joint_1: `traffic_mem_bundle_vs_direct => controller_service_deficit_proxy; controller-pressure=controller service-deficit proxy (source=service_deficit->service_deficit, backpressure-delta=0.199, composite-delta=340.500)`
- top_joint_2: `traffic_mem_monolithic_vs_hbm => controller_memory_pressure_proxy; controller-pressure=backpressure-backed composite (source=service_deficit->backpressure, backpressure-delta=-39.892, composite-delta=-97.061)`

| compare_kind | dominant_endpoint_pressure_side | dominant_memory_axis | compare_memory_pressure_proxy_source | source_authority_tier_transition | route_memory_overlap_mode_transition | most_pressured_controller_backpressure_proxy_delta | most_pressured_controller_memory_pressure_proxy_delta | dominant_backlog_region | dominant_home_access_class | dataflow_controller_alignment_transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | pe_nic | controller_service_deficit_proxy | service_deficit | bootstrap_manifest->bootstrap_manifest | bootstrap_bound->bootstrap_bound | 0.199 | 340.500 | stream_region | same_xy_cross_tier | stable |
| traffic_mem_monolithic_vs_hbm | pe_nic | controller_memory_pressure_proxy | backpressure | bootstrap_manifest->bootstrap_manifest | bootstrap_bound->bootstrap_bound | -39.892 | -97.061 | unavailable | same_xy_cross_tier | alignment_improved |

## Runtime Control Closure

- row_count: `1`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- trigger_alignment_counts: `{"controller_pressure_to_memory_coupling_trigger": 1}`
- dominant_runtime_axis_counts: `{"memory_barrier_coupling_proxy": 1}`
- action_effect_classification_counts: `{"beneficial": 1}`
- dominant_action_effect_classification: `beneficial`
- top_closure_1: `runtime_adaptive_vs_full_3d <= traffic_mem_bundle_vs_direct; controller_pressure_to_memory_coupling_trigger`

| runtime_compare_kind | route_compare_kind | route_dominant_memory_axis | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | trigger_alignment | action_effect_classification | action_effect_evidence | dominant_runtime_axis | closure_interpretation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | traffic_mem_bundle_vs_direct | controller_service_deficit_proxy | executed_control | hybrid | memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure | controller_pressure_to_memory_coupling_trigger | beneficial | aligned_runtime_control_with_visible_actions | memory_barrier_coupling_proxy | pressure -> runtime decision -> outcome: traffic_mem_bundle_vs_direct exposes controller service-deficit proxy (source=service_deficit->service_deficit, backpressure-delta=0.199, composite-delta=340.500); runtime runtime_adaptive_vs_full_3d selects executed_control via hybrid, triggers=memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure, and lands on memory_barrier_coupling_proxy (memory_thermal_delta=-22.633, memory_barrier_delta=69704.000, homeroute_delta=2.000, thermal_guard_delta=2.000); alignment=controller_pressure_to_memory_coupling_trigger; effect=beneficial (aligned_runtime_control_with_visible_actions). |
