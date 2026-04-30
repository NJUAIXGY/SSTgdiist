# Home-Access / Stack-Pressure Co-Design

Bundle vs Direct evidence:
- remote_home_total_demands_delta = -498
- same_xy_cross_tier_total_demands_delta = 3162
- most_pressured_stack_service_deficit_delta = 1362
- most_pressured_controller_service_deficit_proxy_delta = 340.500000
- stack_service_deficit_skew_delta = -0.000298

Monolithic vs HBM evidence:
- remote_home_total_demands_delta = -832
- active_stack_utilization_delta = 0.000000
- most_pressured_stack_service_deficit_delta = -397
- most_pressured_controller_service_deficit_proxy_delta = -99.250000
- runtime_pressure_transfer_kind_transition = runtime_class_unresolved -> cross_class_transfer
- pe_nic_home_stack_demands_total_delta = 0
- synapse_home_stack_service_deficit_total_delta = -509

| Case | Memory | Path Auth | Controller Auth | Home Controllers | Home Class | Dataflow Initiator | Transfer Kind | Dominant Home Stack | Tier-Local Home Demands | Same-XY Cross-Tier Demands | Remote-Home Demands | PE/NIC Home Demands | Synapse Home Deficit | Active Stack Utilization | Hot-Stack Service Deficit | Controller Proxy Deficit | Stack Service-Deficit Skew |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d | hbm_like | real_home_stack_binding | runtime_controller | 0,1,2,3 | remote_home | pe_nic_to_home_stack | runtime_class_unresolved | 0 | 512 | 512 | 1024 | 2048 | 509 | 1.000 | 397 | 99.250 | 1.033 |
| full_3d_monolithic_proxy | monolithic_like | real_home_stack_binding | runtime_controller | 8,9 | same_xy_cross_tier | pe_nic_to_home_stack | cross_class_transfer | 4 | 512 | 1344 | 192 | 2048 | 0 | 1.000 | 0 | 0.000 | 0.000 |
