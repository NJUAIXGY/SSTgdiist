# Memory/NMC Route Runtime Diff Report

- matrix_label: `balanced_20us`

## Traffic Route Diffs

| compare_kind | base_case_id | compare_case_id | dominant_home_runtime_controller_overlap_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 664 | 349 |

## Window Route Diffs

| run_tag | base_case_id | compare_case_id | dataflow_controller_alignment_transition | pe_nic_dominant_controller_outstanding_requests_accum_delta | synapse_dominant_controller_outstanding_requests_accum_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |
| task_fixed_step_4_10us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |
| task_fixed_step_8_20us | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |
| task_fixed_step_8_20us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |
| task_fixed_step_16_40us | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |
| task_fixed_step_16_40us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 |  | 0 | 0 | 0 | 0 |

## Window Route Mechanism Focus

- row_count: `6`
- dominant_axis_counts: `{"memory_per_step": 1, "step_gate_stall": 5}`
- alignment_transition_counts: `{}`
- stall_on_step_gate_cycles_per_completed_step_delta_sum: `6486.562`
- real_home_path_service_deficit_total_delta_sum: `0`
- controller_outstanding_delta_total_sum: `0`

| run_tag | stall_on_step_gate_cycles_per_completed_step_delta | memory_requests_per_completed_step_delta | controller_outstanding_delta_total | real_home_path_service_deficit_total_delta | dataflow_controller_alignment_transition | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- | --- |
| task_fixed_step_4_10us | 127.000 | 151.000 | 0 | 0 |  | memory_per_step |
| task_fixed_step_4_10us_sp64 | 4952.750 | 216.000 | 0 | 0 |  | step_gate_stall |
| task_fixed_step_8_20us | -3986.000 | 75.500 | 0 | 0 |  | step_gate_stall |
| task_fixed_step_8_20us_sp64 | 4923.875 | 111.000 | 0 | 0 |  | step_gate_stall |
| task_fixed_step_16_40us | -1993.000 | 37.750 | 0 | 0 |  | step_gate_stall |
| task_fixed_step_16_40us_sp64 | 2461.938 | 55.500 | 0 | 0 |  | step_gate_stall |

## Window Stop Progression

- row_count: `6`
- compare_kind_counts: `{"window_stop_bundle_vs_direct": 3, "window_stop_monolithic_vs_direct": 3}`
- dominant_axis_counts: `{"controller_outstanding": 6}`
- earliest_same_controller_overlap_stop_at: `10us`
- max_steps_completed_delta: `225`

| compare_kind | stop_at | steps_completed_delta | same_controller_overlap_delta | stall_on_step_gate_cycles_per_completed_step_delta | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- |
| window_stop_bundle_vs_direct | 2us | 0 | 0 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 2us | 27 | 0 | 0.000 | controller_outstanding |
| window_stop_bundle_vs_direct | 10us | 64 | 1 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 10us | 225 | 0 | 0.000 | controller_outstanding |
| window_stop_bundle_vs_direct | 20us | 64 | 1 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 20us | 225 | 0 | 0.000 | controller_outstanding |

## Runtime Compare Signals

- row_count: `2`
- compare_kind_counts: `{"runtime_adaptive_vs_mapping": 1, "runtime_adaptive_vs_thermal_guard": 1}`
- dominant_axis_counts: `{"thermal_guard_actions": 2}`
- vertical_link_pressure_delta_sum: `0.094`
- homeroute_adjustment_count_delta_sum: `4.000`

| compare_kind | vertical_link_pressure_delta | stack_hotspot_penalty_delta | homeroute_adjustment_count_delta | thermal_guard_actions_delta | dominant_runtime_axis |
| --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_mapping | 0.000 | 0.232 | 2.000 | 2.000 | thermal_guard_actions |
| runtime_adaptive_vs_thermal_guard | 0.094 | 0.232 | 2.000 | 2.000 | thermal_guard_actions |

## Mechanism Progression

- progression_signature: `step_gate_stall -> controller_outstanding -> thermal_guard_actions`
- window_route_dominant_axis: `step_gate_stall`
- window_stop_dominant_axis: `controller_outstanding`
- runtime_compare_dominant_axis: `thermal_guard_actions`
- earliest_same_controller_overlap_stop_at: `10us`
- phase_transition_flags: `{"route_to_runtime_axis_shift": true, "route_to_stop_axis_shift": true, "same_controller_overlap_emerged": true, "stop_to_runtime_axis_shift": true}`
- progression_interpretation: `fixed-step window-route is dominated by step_gate_stall; stop-window shifts to controller_outstanding, and same-controller overlap appears at 10us; runtime compare shifts to thermal_guard_actions.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 6 | step_gate_stall | no | alignment={} |
| 2 | window_stop | 6 | controller_outstanding | yes | same_controller_overlap@10us |
| 3 | runtime_compare | 2 | thermal_guard_actions | yes | compare_kinds={"runtime_adaptive_vs_mapping": 1, "runtime_adaptive_vs_thermal_guard": 1} |

## Route/Memory Joint Pressure

- row_count: `2`
- compare_kind_counts: `{"traffic_mem_bundle_vs_direct": 1, "traffic_mem_monolithic_vs_hbm": 1}`
- dominant_endpoint_counts: `{"pe_nic": 2}`
- dominant_memory_axis_counts: `{"service_deficit": 1, "reliability_penalty": 1}`
- dominant_backlog_region_counts: `{"synapse_gather": 1, "unavailable": 1}`

| compare_kind | dominant_endpoint_pressure_side | dominant_memory_axis | dominant_backlog_region | dominant_home_access_class | dataflow_controller_alignment_transition |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | pe_nic | service_deficit | synapse_gather | same_xy_cross_tier | alignment_improved |
| traffic_mem_monolithic_vs_hbm | pe_nic | reliability_penalty | unavailable | same_xy_cross_tier | alignment_improved |
