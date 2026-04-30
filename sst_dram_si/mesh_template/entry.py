from __future__ import annotations

import os
from typing import Any, Dict

from .build import build_mesh_4x4
from .runtime import MeshRuntime
from .runtime import _EnvPatch
from .runtime import resolve_runtime
from .utils import mesh_print


def run_mesh_4x4(*, sst_module: Any, script_file: str) -> Dict[str, Any]:
    """
    One-shot entry to build the 4x4 mesh template with a fully-resolved runtime.
    """

    rt: MeshRuntime = resolve_runtime(sst_module=sst_module, script_file=script_file)

    spec_path = (os.environ.get("MESH_SPEC_JSON") or "").strip()
    if spec_path:
        # Spec-first: seal known legacy env drift keys so the spec
        # remains the only modeling input.
        env_patch = {
            "MESH_BCSR_DIR": None,
            "MESH_GCSS_DIR": None,
            "MESH_GCSS2_DIR": None,
            "MESH_GCSSVLF_DIR": None,
            "MESH_GCSSPLP_DIR": None,
            "MESH_GCSSPLP_PROFILE_EXPORT_ENABLE": None,
            "MESH_GCSSPLP_PROFILE_EXPORT_DIR": None,
            "MESH_SYNAPSE_WEIGHT_MODE": None,
            "MESH_BASE_ADDR_SHIFT": None,
            "MESH_FREEZE_READONLY": None,
            "MESH_READONLY_V_THRESH": None,
            "MESH_READONLY_TAU_MEM": None,
            "MESH_WORKLOAD_IMPL": None,
            "MESH_WORKLOAD_STATS_MODULES": None,
            "MESH_MINIMAL_CORE_PARAMS": None,
            "MESH_GAS_STEP_SEQ_GATE_ENABLE": None,
            "MESH_GLOBAL_STEP_DONE_POLICY": None,
            "MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES": None,
            "MESH_GLOBAL_STEP_QUIESCENT_MIN_CYCLES": None,
            "MESH_GLOBAL_STEP_FIXED_CYCLES": None,
            "MESH_GLOBAL_STEP_READY_DELAY_CYCLES": None,
            "MESH_MAPPING_MODE": None,
            "MESH_DENSE_STRICT_CACHELINE": None,
            "MESH_GAS_FORCE_DEFER": None,
            "SNNDL_APPLY_DENSE_ACC": None,
            "SNNDL_ACC_SHADOW_VERIFY": None,
        }
        with _EnvPatch(env_patch):
            built = build_mesh_4x4(
                run_output_dir=rt.run_output_dir,
                weights_dir=rt.weights_dir,
                node_limit=rt.node_limit,
                mesh_size=rt.mesh_size,
                layers=rt.layers_cfg,
                mesh=rt.mesh_cfg,
                flags=rt.flags_cfg,
                mem_layout=rt.mem_layout_cfg,
                gas=rt.gas_cfg,
                step=rt.step_cfg,
                routing=rt.routing_cfg,
                debug=rt.debug_cfg,
                loader=rt.loader_cfg,
                global_step_ctrl=rt.global_step_ctrl,
                spike_source_enabled=rt.spike_source_enabled,
                spike_data_files=rt.spike_data_files,
                debug_conn=rt.debug_conn,
                overrides=rt.overrides,
            )
    else:
        built = build_mesh_4x4(
            run_output_dir=rt.run_output_dir,
            weights_dir=rt.weights_dir,
            node_limit=rt.node_limit,
            mesh_size=rt.mesh_size,
            layers=rt.layers_cfg,
            mesh=rt.mesh_cfg,
            flags=rt.flags_cfg,
            mem_layout=rt.mem_layout_cfg,
            gas=rt.gas_cfg,
            step=rt.step_cfg,
            routing=rt.routing_cfg,
            debug=rt.debug_cfg,
            loader=rt.loader_cfg,
            global_step_ctrl=rt.global_step_ctrl,
            spike_source_enabled=rt.spike_source_enabled,
            spike_data_files=rt.spike_data_files,
            debug_conn=rt.debug_conn,
            overrides=rt.overrides,
        )

    try:
        mesh_print(f"✅ 创建{len(built.get('pe_memory_controllers', []))}个独立PE内存控制器和{len(built.get('pe_memory_buses', []))}个内存总线")
        mesh_print(f"✅ 创建{len(built.get('routers', []))}个路由器完成")
        mesh_print(f"✅ 完成{len(built.get('nics', []))}个NIC连接和{int(built.get('router_connection_count', 0))}个路由器连接")
        if built.get("spike_sources"):
            mesh_print(f"✅ 完成{len(built.get('spike_sources', []))}个SpikeSource到输入层连接")
    except Exception:
        pass

    # === 配置仿真 ===
    sst_module.setProgramOption("timebase", "1ps")
    # step-limited runs are ended by GlobalGasStepController(max_steps); do not force stop-at.
    if rt.max_steps <= 0 and rt.sim_stop_ns <= 0:
        sst_module.setProgramOption("stop-at", rt.simulation_time)

    mesh_print(f"\n🚀 启动4x4分层网络仿真（时长: {rt.simulation_time}）...")
    return {"runtime": rt, "built": built}
