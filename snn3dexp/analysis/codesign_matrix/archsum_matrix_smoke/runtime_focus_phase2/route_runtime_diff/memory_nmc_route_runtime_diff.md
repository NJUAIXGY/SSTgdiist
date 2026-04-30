# Memory/NMC Route Runtime Diff Report

- matrix_label: `archsum_matrix_smoke`

## Traffic Route Diffs

_None_

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

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_axis_counts: `{}`
- earliest_same_controller_overlap_stop_at: ``
- max_steps_completed_delta: `0`

_None_

## Runtime Compare Signals

- row_count: `2`
- compare_kind_counts: `{"runtime_adaptive_vs_mapping": 1, "runtime_adaptive_vs_thermal_guard": 1}`
- dominant_axis_counts: `{"thermal_guard_actions": 2}`
- vertical_link_pressure_delta_sum: `0.094`
- route_thermal_coupling_score_delta_sum: `0.000`
- memory_thermal_coupling_proxy_delta_sum: `0.000`
- memory_barrier_coupling_proxy_delta_sum: `0.000`
- homeroute_adjustment_count_delta_sum: `4.000`

| compare_kind | vertical_link_pressure_delta | stack_hotspot_penalty_delta | route_thermal_coupling_score_delta | memory_thermal_coupling_proxy_delta | memory_barrier_coupling_proxy_delta | homeroute_adjustment_count_delta | thermal_guard_actions_delta | dominant_runtime_axis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_mapping | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 2.000 | 2.000 | thermal_guard_actions |
| runtime_adaptive_vs_thermal_guard | 0.094 | 0.000 | 0.000 | 0.000 | 0.000 | 2.000 | 2.000 | thermal_guard_actions |

## Mechanism Progression

- progression_signature: `controller_outstanding -> unavailable -> thermal_guard_actions`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `unavailable`
- runtime_compare_dominant_axis: `thermal_guard_actions`
- earliest_same_controller_overlap_stop_at: ``
- phase_transition_flags: `{"route_to_runtime_axis_shift": true, "route_to_stop_axis_shift": false, "same_controller_overlap_emerged": false, "stop_to_runtime_axis_shift": false}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window evidence is unavailable; runtime compare is dominated by thermal_guard_actions.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 6 | controller_outstanding | no | alignment={"alignment_improved": 1, "stable": 5} |
| 2 | window_stop | 0 | unavailable | no | same_controller_overlap@unavailable |
| 3 | runtime_compare | 2 | thermal_guard_actions | no | compare_kinds={"runtime_adaptive_vs_mapping": 1, "runtime_adaptive_vs_thermal_guard": 1} |

## Route/Memory Joint Pressure

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_endpoint_counts: `{}`
- dominant_memory_axis_counts: `{}`
- dominant_backlog_region_counts: `{}`

_None_
