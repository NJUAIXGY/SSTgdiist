# Home-Access / Stack-Pressure Co-Design

Bundle vs Direct evidence:
- remote_home_total_demands_delta = 0
- same_xy_cross_tier_total_demands_delta = 0
- most_pressured_stack_service_deficit_delta = 0
- most_pressured_controller_service_deficit_proxy_delta = 0.000000
- stack_service_deficit_skew_delta = 0.000000

Monolithic vs HBM evidence:
- remote_home_total_demands_delta = 96
- active_stack_utilization_delta = 0.000000
- most_pressured_stack_service_deficit_delta = 0
- most_pressured_controller_service_deficit_proxy_delta = 0.000000

| Case | Memory | Home Class | Dominant Home Stack | Tier-Local Home Demands | Same-XY Cross-Tier Demands | Remote-Home Demands | Active Stack Utilization | Hot-Stack Service Deficit | Controller Proxy Deficit | Stack Service-Deficit Skew |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d_snn_window | hbm_like | tier_local_home | 0 | 64 | 64 | 0 | 1.000 | 0 | 0.000 | 0.000 |
| full_3d_snn_window_monolithic_proxy | monolithic_like | tier_local_home | 0 | 192 | 0 | 96 | 1.000 | 0 | 0.000 | 0.000 |
