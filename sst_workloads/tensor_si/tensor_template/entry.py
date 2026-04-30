from __future__ import annotations

from typing import Any, Dict

from .build import build_tensor_mesh_4x4
from .runtime import TensorMeshRuntime
from .runtime import resolve_runtime
from .utils import tensor_print


def run_tensor_mesh_4x4(*, sst_module: Any, script_file: str) -> Dict[str, Any]:
    rt: TensorMeshRuntime = resolve_runtime(sst_module=sst_module, script_file=script_file)

    built = build_tensor_mesh_4x4(
        run_output_dir=rt.run_output_dir,
        node_limit=rt.node_limit,
        mesh_size=rt.mesh_size,
        mesh_cfg=rt.mesh_cfg,
        tensor_cfg=rt.tensor_cfg,
        overrides=rt.overrides,
    )

    sst_module.setProgramOption("timebase", "1ps")
    sst_module.setProgramOption("stop-at", rt.simulation_time)
    tensor_print(f"[tensor_mesh] start sim: {rt.simulation_time}")
    return {"runtime": rt, "built": built}
