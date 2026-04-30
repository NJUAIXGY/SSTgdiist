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
