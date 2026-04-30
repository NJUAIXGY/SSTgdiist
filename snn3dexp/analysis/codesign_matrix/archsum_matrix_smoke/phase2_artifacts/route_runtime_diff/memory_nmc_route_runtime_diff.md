# Memory/NMC Route Runtime Diff Report

- matrix_label: `archsum_matrix_smoke`

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

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_axis_counts: `{}`
- earliest_same_controller_overlap_stop_at: ``
- max_steps_completed_delta: `0`

_None_

## Runtime Compare Signals

- row_count: `1`
- compare_kind_counts: `{"runtime_adaptive_vs_full_3d": 1}`
- dominant_axis_counts: `{"memory_barrier_coupling_proxy": 1}`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- compare_control_trigger_signal_counts: `{"memory_barrier_coupling_proxy": 1, "memory_thermal_coupling_proxy": 1, "route_memory_overlap": 1, "vertical_link_pressure": 1}`
- vertical_link_pressure_delta_sum: `0.238`
- route_thermal_coupling_score_delta_sum: `0.102`
- memory_thermal_coupling_proxy_delta_sum: `-0.172`
- memory_barrier_coupling_proxy_delta_sum: `69704.000`
- homeroute_adjustment_count_delta_sum: `2.000`

| compare_kind | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | vertical_link_pressure_delta | stack_hotspot_penalty_delta | route_thermal_coupling_score_delta | memory_thermal_coupling_proxy_delta | memory_barrier_coupling_proxy_delta | homeroute_adjustment_count_delta | thermal_guard_actions_delta | dominant_runtime_axis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | executed_control | hybrid | memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure | 0.238 | 0.132 | 0.102 | -0.172 | 69704.000 | 2.000 | 2.000 | memory_barrier_coupling_proxy |

## Mechanism Progression

- progression_signature: `controller_outstanding -> unavailable -> memory_barrier_coupling_proxy`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `unavailable`
- runtime_compare_dominant_axis: `memory_barrier_coupling_proxy`
- earliest_same_controller_overlap_stop_at: ``
- phase_transition_flags: `{"route_to_runtime_axis_shift": true, "route_to_stop_axis_shift": false, "same_controller_overlap_emerged": false, "stop_to_runtime_axis_shift": false}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window evidence is unavailable; runtime compare is dominated by memory_barrier_coupling_proxy.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 6 | controller_outstanding | no | alignment={"alignment_improved": 1, "stable": 5} |
| 2 | window_stop | 0 | unavailable | no | same_controller_overlap@unavailable |
| 3 | runtime_compare | 1 | memory_barrier_coupling_proxy | no | compare_kinds={"runtime_adaptive_vs_full_3d": 1} |

## Route/Memory Joint Pressure

- row_count: `2`
- compare_kind_counts: `{"traffic_mem_bundle_vs_direct": 1, "traffic_mem_monolithic_vs_hbm": 1}`
- dominant_endpoint_counts: `{"pe_nic": 1, "mixed": 1}`
- dominant_memory_axis_counts: `{"controller_memory_pressure_proxy": 2}`
- dominant_backlog_region_counts: `{"unavailable": 2}`
- base_memory_pressure_proxy_source_counts: `{"backpressure": 2}`
- compare_memory_pressure_proxy_source_counts: `{"backpressure": 2}`
- memory_pressure_proxy_source_transition_counts: `{"backpressure->backpressure": 2}`
- most_pressured_controller_backpressure_proxy_delta_sum: `-1.143`
- most_pressured_controller_memory_pressure_proxy_delta_sum: `-1.143`
- top_joint_1: `traffic_mem_monolithic_vs_hbm => controller_memory_pressure_proxy; controller-pressure=backpressure-backed composite (source=backpressure->backpressure, backpressure-delta=-5.021, composite-delta=-5.021)`
- top_joint_2: `traffic_mem_bundle_vs_direct => controller_memory_pressure_proxy; controller-pressure=backpressure-backed composite (source=backpressure->backpressure, backpressure-delta=3.879, composite-delta=3.879)`

| compare_kind | dominant_endpoint_pressure_side | dominant_memory_axis | compare_memory_pressure_proxy_source | most_pressured_controller_backpressure_proxy_delta | most_pressured_controller_memory_pressure_proxy_delta | dominant_backlog_region | dominant_home_access_class | dataflow_controller_alignment_transition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | pe_nic | controller_memory_pressure_proxy | backpressure | 3.879 | 3.879 | unavailable | same_xy_cross_tier | stable |
| traffic_mem_monolithic_vs_hbm | mixed | controller_memory_pressure_proxy | backpressure | -5.021 | -5.021 | unavailable | same_xy_cross_tier | alignment_improved |

## Runtime Control Closure

- row_count: `1`
- compare_control_decision_counts: `{"executed_control": 1}`
- compare_control_decision_source_counts: `{"hybrid": 1}`
- trigger_alignment_counts: `{"controller_pressure_to_memory_coupling_trigger": 1}`
- dominant_runtime_axis_counts: `{"memory_barrier_coupling_proxy": 1}`
- top_closure_1: `runtime_adaptive_vs_full_3d <= traffic_mem_monolithic_vs_hbm; controller_pressure_to_memory_coupling_trigger`

| runtime_compare_kind | route_compare_kind | route_dominant_memory_axis | compare_control_decision | compare_control_decision_source | compare_control_trigger_signals_csv | trigger_alignment | dominant_runtime_axis | closure_interpretation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runtime_adaptive_vs_full_3d | traffic_mem_monolithic_vs_hbm | controller_memory_pressure_proxy | executed_control | hybrid | memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure | controller_pressure_to_memory_coupling_trigger | memory_barrier_coupling_proxy | pressure -> runtime decision -> outcome: traffic_mem_monolithic_vs_hbm exposes backpressure-backed composite (source=backpressure->backpressure, backpressure-delta=-5.021, composite-delta=-5.021); runtime runtime_adaptive_vs_full_3d selects executed_control via hybrid, triggers=memory_barrier_coupling_proxy|memory_thermal_coupling_proxy|route_memory_overlap|vertical_link_pressure, and lands on memory_barrier_coupling_proxy (memory_thermal_delta=-0.172, memory_barrier_delta=69704.000, homeroute_delta=2.000, thermal_guard_delta=2.000); alignment=controller_pressure_to_memory_coupling_trigger. |
