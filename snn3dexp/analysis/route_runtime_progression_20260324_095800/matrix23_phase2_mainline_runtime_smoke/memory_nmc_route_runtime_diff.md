# Memory/NMC Route Runtime Diff Report

- matrix_label: `matrix23_phase2_mainline_runtime_smoke`

## Traffic Route Diffs

| compare_kind | base_case_id | compare_case_id | dominant_home_runtime_controller_overlap_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- |
| traffic_mem_bundle_vs_direct | full_3d | full_3d_tile_bundle_v3 | 0 | 845 | 465 |

## Window Route Diffs

| run_tag | base_case_id | compare_case_id | dataflow_controller_alignment_transition | pe_nic_dominant_controller_outstanding_requests_accum_delta | synapse_dominant_controller_outstanding_requests_accum_delta | pe_nic_real_home_path_service_deficit_total_delta | synapse_real_home_path_service_deficit_total_delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| matrix23_phase2_mainline_runtime_fixed_step_4_2us | full_3d_snn_window | full_3d_snn_window_bundle_v3 | alignment_degraded | -155821 | -155821 | 8 | 0 |

## Window Route Mechanism Focus

- row_count: `1`
- dominant_axis_counts: `{"controller_outstanding": 1}`
- alignment_transition_counts: `{"alignment_degraded": 1}`
- stall_on_step_gate_cycles_per_completed_step_delta_sum: `6528.000`
- real_home_path_service_deficit_total_delta_sum: `8`
- controller_outstanding_delta_total_sum: `-311642`

| run_tag | stall_on_step_gate_cycles_per_completed_step_delta | memory_requests_per_completed_step_delta | controller_outstanding_delta_total | real_home_path_service_deficit_total_delta | dataflow_controller_alignment_transition | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- | --- |
| matrix23_phase2_mainline_runtime_fixed_step_4_2us | 6528.000 | 678.000 | -311642 | 8 | alignment_degraded | controller_outstanding |

## Window Stop Progression

- row_count: `4`
- compare_kind_counts: `{"window_stop_bundle_vs_direct": 2, "window_stop_monolithic_vs_direct": 2}`
- dominant_axis_counts: `{"controller_outstanding": 4}`
- earliest_same_controller_overlap_stop_at: `10us`
- max_steps_completed_delta: `225`

| compare_kind | stop_at | steps_completed_delta | same_controller_overlap_delta | stall_on_step_gate_cycles_per_completed_step_delta | dominant_mechanism_axis |
| --- | --- | --- | --- | --- | --- |
| window_stop_bundle_vs_direct | 2us | 0 | 0 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 2us | 27 | 0 | 0.000 | controller_outstanding |
| window_stop_bundle_vs_direct | 10us | 64 | 1 | 0.000 | controller_outstanding |
| window_stop_monolithic_vs_direct | 10us | 225 | 0 | 0.000 | controller_outstanding |

## Runtime Compare Signals

- row_count: `0`
- compare_kind_counts: `{}`
- dominant_axis_counts: `{}`
- vertical_link_pressure_delta_sum: `0.000`
- homeroute_adjustment_count_delta_sum: `0.000`

_None_

## Mechanism Progression

- progression_signature: `controller_outstanding -> controller_outstanding -> unavailable`
- window_route_dominant_axis: `controller_outstanding`
- window_stop_dominant_axis: `controller_outstanding`
- runtime_compare_dominant_axis: `unavailable`
- earliest_same_controller_overlap_stop_at: `10us`
- phase_transition_flags: `{"route_to_runtime_axis_shift": false, "route_to_stop_axis_shift": false, "same_controller_overlap_emerged": true, "stop_to_runtime_axis_shift": false}`
- progression_interpretation: `fixed-step window-route is dominated by controller_outstanding; stop-window remains controller_outstanding, and same-controller overlap appears at 10us; runtime compare evidence is unavailable.`

| phase | row_count | dominant_axis | key_signal |
| --- | --- | --- | --- |
| window_route | 1 | controller_outstanding | alignment={"alignment_degraded": 1} |
| window_stop | 4 | controller_outstanding | same_controller_overlap@10us |
| runtime_compare | 0 | unavailable | compare_kinds={} |
