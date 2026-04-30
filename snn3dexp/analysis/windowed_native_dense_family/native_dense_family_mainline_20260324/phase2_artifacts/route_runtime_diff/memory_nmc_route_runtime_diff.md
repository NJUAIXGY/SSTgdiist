# Memory/NMC Route Runtime Diff Report

- matrix_label: `native_dense_fixed_step_8_20us`

## Traffic Route Diffs

_None_

## Window Route Diffs

| run_tag | base_case_id | compare_case_id | dataflow_controller_alignment_transition | pe_nic_dominant_controller_outstanding_requests_accum_delta | synapse_dominant_controller_outstanding_requests_accum_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| native_dense_fixed_step_4_10us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | alignment_improved | -356163 | -355581 | 0 | 0 |
| native_dense_fixed_step_4_10us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -2368 | -3856 | 0 | 0 |
| native_dense_fixed_step_8_20us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -1181289 | -1180707 | 0 | 0 |
| native_dense_fixed_step_8_20us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | 107851 | 105481 | 0 | 0 |
| native_dense_fixed_step_16_40us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | -1181289 | -1180707 | 0 | 0 |
| native_dense_fixed_step_16_40us_sp64 | full_3d_snn_window | full_3d_snn_window_bundle_v3 | stable | 107851 | 105481 | 0 | 0 |

## Window Route Mechanism Focus

- row_count: `6`
- dominant_axis_counts: `{"controller_outstanding": 5, "step_gate_stall": 1}`
- alignment_transition_counts: `{"alignment_improved": 1, "stable": 5}`
- stall_on_step_gate_cycles_per_completed_step_delta_sum: `38269.333`
- real_home_path_service_deficit_total_delta_sum: `0`
- controller_outstanding_delta_total_sum: `-5015296`

| run_tag | stall_on_step_gate_cycles_per_completed_step_delta | memory_requests_per_completed_step_delta | controller_outstanding_delta_total | real_home_path_service_deficit_total_delta | dataflow_controller_alignment_transition | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- | --- |
| native_dense_fixed_step_4_10us | 13576.667 | 478.667 | -711744 | 0 | alignment_improved | controller_outstanding |
| native_dense_fixed_step_4_10us_sp64 | 6584.667 | 730.667 | -6224 | 0 | stable | step_gate_stall |
| native_dense_fixed_step_8_20us | 9602.625 | 129.500 | -2361996 | 0 | stable | controller_outstanding |
| native_dense_fixed_step_8_20us_sp64 | 2469.375 | 168.000 | 213332 | 0 | stable | controller_outstanding |
| native_dense_fixed_step_16_40us | 4801.312 | 64.750 | -2361996 | 0 | stable | controller_outstanding |
| native_dense_fixed_step_16_40us_sp64 | 1234.688 | 84.000 | 213332 | 0 | stable | controller_outstanding |

## Window Stop Progression

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_axis_counts: `{}`
- earliest_same_controller_overlap_stop_at: ``
- max_steps_completed_delta: `0`

_None_

## Runtime Compare Signals

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_axis_counts: `{}`
- vertical_link_pressure_delta_sum: `0.000`
- homeroute_adjustment_count_delta_sum: `0.000`

_None_

## Mechanism Progression

- progression_signature: `controller_outstanding -> unavailable -> unavailable`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `unavailable`
- runtime_compare_dominant_axis: `unavailable`
- earliest_same_controller_overlap_stop_at: ``
- phase_transition_flags: `{"route_to_runtime_axis_shift": false, "route_to_stop_axis_shift": false, "same_controller_overlap_emerged": false, "stop_to_runtime_axis_shift": false}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window evidence is unavailable; runtime compare evidence is unavailable.`

| phase_order | phase | row_count | dominant_axis | phase_transition_from_previous | key_signal |
| --- | --- | --- | --- | --- | --- |
| 1 | window_route | 6 | controller_outstanding | no | alignment={"alignment_improved": 1, "stable": 5} |
| 2 | window_stop | 0 | unavailable | no | same_controller_overlap@unavailable |
| 3 | runtime_compare | 0 | unavailable | no | compare_kinds={} |

## Route/Memory Joint Pressure

- row_count: `1`
- compare_kind_counts: `{"traffic_mem_monolithic_vs_hbm": 1}`
- dominant_endpoint_counts: `{"pe_nic": 1}`
- dominant_memory_axis_counts: `{"vertical_link_pressure": 1}`
- dominant_backlog_region_counts: `{"unavailable": 1}`

| compare_kind | dominant_endpoint_pressure_side | dominant_memory_axis | dominant_backlog_region | dominant_home_access_class | dataflow_controller_alignment_transition |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_monolithic_vs_hbm | pe_nic | vertical_link_pressure | unavailable | tier_local_home | alignment_improved |
