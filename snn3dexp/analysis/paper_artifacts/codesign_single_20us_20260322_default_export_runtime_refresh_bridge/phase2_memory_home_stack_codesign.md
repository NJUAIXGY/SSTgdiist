# Home-Access / Stack-Pressure Co-Design

Bundle vs Direct evidence:
- remote_home_total_demands_delta = -19544
- same_xy_cross_tier_total_demands_delta = 123302
- most_pressured_stack_service_deficit_delta = 52014
- most_pressured_controller_service_deficit_proxy_delta = 0.000000
- stack_service_deficit_skew_delta = -0.002550

Monolithic vs HBM evidence:
- remote_home_total_demands_delta = -32500
- active_stack_utilization_delta = 0.000000
- most_pressured_stack_service_deficit_delta = -17807
- most_pressured_controller_service_deficit_proxy_delta = 0.000000

| Case | Memory | Home Class | Dominant Home Stack | Tier-Local Home Demands | Same-XY Cross-Tier Demands | Remote-Home Demands | Active Stack Utilization | Hot-Stack Service Deficit | Controller Proxy Deficit | Stack Service-Deficit Skew |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_3d | hbm_like | remote_home | -1 | 20000 | 20000 | 40000 | 1.000 | 22823 | 0.000 | 1.006 |
| full_3d_monolithic_proxy | monolithic_like | same_xy_cross_tier | -1 | 20000 | 52500 | 7500 | 1.000 | 5016 | 0.000 | 1.000 |
