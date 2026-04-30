| Case | Mesh | NoC | Memory | Status | Mapping | Same-Home | Vertical-Target | Vertical-Hops | Remote-Home | Vertical-Pressure | Hotspot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline 2D | 4x4x1 | MulticastRouter | legacy_per_pe | composed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Memory-Only 3D | 4x4x2 | MulticastRouter | hbm_like | composed | xy_neighbor | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 | 1.250 |
| NoC-Only 3D | 4x4x2 | MulticastRouter3DNative | legacy_per_pe | composed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Full 3D | 4x4x2 | MulticastRouter3DNative | hbm_like | composed | z_blind | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 | 1.250 |
| Full 3D + 3D-Aware Mapping | 4x4x2 | MulticastRouter3DNative | hbm_like | composed | 3d_aware | 0.906 | 0.406 | 0.000 | 0.000 | 0.244 | 1.250 |
| Full 3D + Thermal Guard | 4x4x2 | MulticastRouter3DNative | hbm_like | composed | 3d_aware | 0.750 | 0.250 | 0.000 | 0.000 | 0.150 | 1.250 |
| full_3d_monolithic_proxy | 4x4x2 | MulticastRouter3DNative | monolithic_like | composed | 3d_aware | 0.500 | 0.250 | 0.000 | 0.000 | 0.150 | 1.250 |
| full_3d_runtime_adaptive | 4x4x2 | MulticastRouter3DNative | hbm_like | composed | 3d_aware | 0.906 | 0.406 | 0.000 | 0.000 | 0.244 | 1.250 |
