# Memory/NMC Route Runtime Diff Report

- matrix_label: `task4_window_stop_runtime_closure_mainline`

## Traffic Route Diffs

| compare_kind | base_case_id | compare_case_id | dominant_home_runtime_controller_overlap_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 0 | 0 |

## Window Route Diffs

| run_tag | base_case_id | compare_case_id | dataflow_controller_alignment_transition | pe_nic_dominant_controller_outstanding_requests_accum_delta | synapse_dominant_controller_outstanding_requests_accum_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | alignment_improved | -356163 | -355581 | 0 | 0 |
| task_fixed_step_4_10us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -2368 | -3856 | 0 | 0 |
| task_fixed_step_8_20us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -1181289 | -1180707 | 0 | 0 |
| task_fixed_step_8_20us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | 107851 | 105481 | 0 | 0 |
| task_fixed_step_16_40us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -1181289 | -1180707 | 0 | 0 |
| task_fixed_step_16_40us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | 107851 | 105481 | 0 | 0 |

## Window Route Mechanism Focus

- row_count: `6`
- dominant_axis_counts: `{"controller_outstanding": 5, "step_gate_stall": 1}`
- alignment_transition_counts: `{"alignment_improved": 1, "stable": 5}`
- stall_on_step_gate_cycles_per_completed_step_delta_sum: `38269.333`
- real_home_path_service_deficit_total_delta_sum: `0`
- controller_outstanding_delta_total_sum: `-5015296`

| run_tag | stall_on_step_gate_cycles_per_completed_step_delta | memory_requests_per_completed_step_delta | controller_outstanding_delta_total | real_home_path_service_deficit_total_delta | dataflow_controller_alignment_transition | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | 13576.667 | 478.667 | -711744 | 0 | alignment_improved | controller_outstanding |
| task_fixed_step_4_10us_sp64 | 6584.667 | 730.667 | -6224 | 0 | stable | step_gate_stall |
| task_fixed_step_8_20us | 9602.625 | 129.500 | -2361996 | 0 | stable | controller_outstanding |
| task_fixed_step_8_20us_sp64 | 2469.375 | 168.000 | 213332 | 0 | stable | controller_outstanding |
| task_fixed_step_16_40us | 4801.312 | 64.750 | -2361996 | 0 | stable | controller_outstanding |
| task_fixed_step_16_40us_sp64 | 1234.688 | 84.000 | 213332 | 0 | stable | controller_outstanding |

## Window Stop Progression

- row_count: `6`
- compare_kind_counts: `{"window_stop_bundle_vs_direct": 3, "window_stop_monolithic_vs_direct": 3}`
- dominant_axis_counts: `{"stable_or_zero": 6}`
- earliest_same_controller_overlap_stop_at: ``
- max_steps_completed_delta: `0`

| compare_kind | stop_at | steps_completed_delta | same_controller_overlap_delta | stall_on_step_gate_cycles_per_completed_step_delta | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- |
| window_stop_bundle_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |
| window_stop_monolithic_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |
| window_stop_bundle_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |
| window_stop_monolithic_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |
| window_stop_bundle_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |
| window_stop_monolithic_vs_direct |  | 0 | 0 | 0.000 | stable_or_zero |

## Runtime Compare Signals

- row_count: `1`
- compare_kind_counts: `{"runtime_adaptive_vs_full_3d": 1}`
- dominant_axis_counts: `{"thermal_guard_actions": 1}`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- compare_control_trigger_signal_counts: `{"route_memory_overlap": 1, "stack_hotspot_penalty": 1, "vertical_link_pressure": 1}`
- vertical_link_pressure_delta_sum: `0.000`
- route_thermal_coupling_score_delta_sum: `0.000`
- memory_thermal_coupling_proxy_delta_sum: `0.000`
- memory_barrier_coupling_proxy_delta_sum: `0.000`
- homeroute_adjustment_count_delta_sum: `2.000`

| compare_kind | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | vertical_link_pressure_delta | stack_hotspot_penalty_delta | route_thermal_coupling_score_delta | memory_thermal_coupling_proxy_delta | memory_barrier_coupling_proxy_delta | homeroute_adjustment_count_delta | thermal_guard_actions_delta | dominant_runtime_axis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | executed_control | hybrid | route_memory_overlap|stack_hotspot_penalty|vertical_link_pressure | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 2.000 | 2.000 | thermal_guard_actions |

## Mechanism Progression

- progression_signature: `controller_outstanding -> stable_or_zero -> thermal_guard_actions`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `stable_or_zero`
- runtime_compare_dominant_axis: `thermal_guard_actions`
- earliest_same_controller_overlap_stop_at: ``
- phase_transition_flags: `{"route_to_runtime_axis_shift": true, "route_to_stop_axis_shift": true, "same_controller_overlap_emerged": false, "stop_to_runtime_axis_shift": true}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window shifts to stable_or_zero, without same-controller overlap; runtime compare shifts to thermal_guard_actions.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 6 | controller_outstanding | no | alignment={"alignment_improved": 1, "stable": 5} |
| 2 | window_stop | 6 | stable_or_zero | yes | same_controller_overlap@unavailable |
| 3 | runtime_compare | 1 | thermal_guard_actions | yes | compare_kinds={"runtime_adaptive_vs_full_3d": 1} |

## Route/Memory Joint Pressure

- row_count: `2`
- compare_kind_counts: `{"traffic_mem_bundle_vs_direct": 1, "traffic_mem_monolithic_vs_hbm": 1}`
- dominant_endpoint_counts: `{"unavailable": 2}`
- dominant_memory_axis_counts: `{"unavailable": 1, "reliability_penalty": 1}`
- dominant_backlog_region_counts: `{"unavailable": 2}`
- base_memory_pressure_proxy_source_counts: `{}`
- compare_memory_pressure_proxy_source_counts: `{}`
- memory_pressure_proxy_source_transition_counts: `{}`
- most_pressured_controller_backpressure_proxy_delta_sum: `0.000`
- most_pressured_controller_memory_pressure_proxy_delta_sum: `0.000`
- top_joint_1: `traffic_mem_monolithic_vs_hbm => reliability_penalty; controller-pressure=secondary controller pressure (source=unavailable, backpressure-delta=0.000, composite-delta=0.000)`
- top_joint_2: `traffic_mem_bundle_vs_direct => unavailable; controller-pressure=secondary controller pressure (source=unavailable, backpressure-delta=0.000, composite-delta=0.000)`

| compare_kind | dominant_endpoint_pressure_side | dominant_memory_axis | compare_memory_pressure_proxy_source | most_pressured_controller_backpressure_proxy_delta | most_pressured_controller_memory_pressure_proxy_delta | dominant_backlog_region | dominant_home_access_class | dataflow_controller_alignment_transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | unavailable | unavailable |  | 0.000 | 0.000 | unavailable |  | stable |
| traffic_mem_monolithic_vs_hbm | unavailable | reliability_penalty |  | 0.000 | 0.000 | unavailable |  | stable |

## Runtime Control Closure

- row_count: `1`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- trigger_alignment_counts: `{"unclosed_or_unavailable": 1}`
- dominant_runtime_axis_counts: `{"thermal_guard_actions": 1}`
- top_closure_1: `runtime_adaptive_vs_full_3d <= traffic_mem_monolithic_vs_hbm; unclosed_or_unavailable`

| runtime_compare_kind | route_compare_kind | route_dominant_memory_axis | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | trigger_alignment | dominant_runtime_axis | closure_interpretation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | traffic_mem_monolithic_vs_hbm | reliability_penalty | executed_control | hybrid | route_memory_overlap|stack_hotspot_penalty|vertical_link_pressure | unclosed_or_unavailable | thermal_guard_actions | pressure -> runtime decision -> outcome: traffic_mem_monolithic_vs_hbm exposes secondary controller pressure (source=unavailable, backpressure-delta=0.000, composite-delta=0.000); runtime runtime_adaptive_vs_full_3d selects executed_control via hybrid, triggers=route_memory_overlap|stack_hotspot_penalty|vertical_link_pressure, and lands on thermal_guard_actions (memory_thermal_delta=0.000, memory_barrier_delta=0.000, homeroute_delta=2.000, thermal_guard_delta=2.000); alignment=unclosed_or_unavailable. |
