| Case | Mesh | NoC | Memory | Status | Mapping | Same-Home | Vertical-Target | Vertical-Hops | Remote-Home | Vertical-Pressure | Hotspot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline 2D | 4x4x1 | MulticastRouter | legacy_per_pe | smoke_passed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Memory-Only 3D | 4x4x2 | MulticastRouter | hbm_like | smoke_passed | xy_neighbor | 0.500 | 0.000 | 0.500 | 0.500 | 0.200 | 1.250 |
| NoC-Only 3D | 4x4x2 | MulticastRouter3DNative | legacy_per_pe | smoke_passed | z_mirror | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Full 3D | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | z_blind | 0.500 | 0.000 | 0.500 | 0.500 | 0.200 | 1.216 |
| Full 3D + 3D-Aware Mapping | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.906 | 0.406 | 0.500 | 0.500 | 0.444 | 1.215 |
| Full 3D + Thermal Guard | 4x4x2 | MulticastRouter3DNative | hbm_like | smoke_passed | 3d_aware | 0.750 | 0.250 | 0.500 | 0.500 | 0.350 | 1.215 |
