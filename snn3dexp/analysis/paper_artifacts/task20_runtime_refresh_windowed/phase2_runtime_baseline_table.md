| Case | Mesh | NoC | Memory | Status | Mapping | Same-Home | Vertical-Target | Vertical-Hops | Remote-Home | Vertical-Pressure | Hotspot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline 2D | 4x4x1 | MulticastRouter | legacy_per_pe | composed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Memory-Only 3D | 4x4x2 | MulticastRouter | hbm_like | smoke_passed | xy_neighbor | 0.500 | 0.000 | 0.500 | 0.500 | 0.200 | 1.250 |
| NoC-Only 3D | 4x4x2 | MulticastRouter3DNative | legacy_per_pe | composed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Full 3D | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | z_blind | 0.500 | 0.000 | 0.436 | 0.500 | 0.190 | 1.237 |
| Full 3D + Monolithic Proxy | 4x4x2 | MulticastRouter3DNative | monolithic_like | smoke_passed | 3d_aware | 0.500 | 0.250 | 0.000 | 0.000 | 0.150 | 1.250 |
| Full 3D + Tile Bundle v3 | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.906 | 0.406 | 0.436 | 0.500 | 0.434 | 1.234 |
| Full 3D + 3D-Aware Mapping | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.906 | 0.406 | 0.500 | 0.500 | 0.444 | 1.215 |
| Full 3D + Thermal Guard | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.750 | 0.250 | 0.500 | 0.500 | 0.350 | 1.215 |
| Full 3D + Runtime Adaptive | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.906 | 0.406 | 0.500 | 0.500 | 0.444 | 1.250 |
| NoC-Only 3D + Bundle Fault v3 | 4x4x2 | MulticastRouter3DNative | legacy_per_pe | smoke_passed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
