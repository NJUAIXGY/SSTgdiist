from __future__ import annotations

import os
from typing import Any, Optional


def resolve_step_activation_template(
    *,
    template_override: str,
    global_bcsr_available: bool,
    global_bcsr_dir: str,
) -> str:
    if template_override:
        # 允许传入包含 {pe} 与 {core} 的模板；不在此处替换 {pe}
        return template_override
    if global_bcsr_available:
        return os.path.join(global_bcsr_dir, "pe{pe:02d}", "core{core:02d}.bcsr.bin")
    return ""


def step_bcsr_offsets_ready(
    *,
    rowptr_offset: Optional[int],
    colidx_offset: Optional[int],
    blockdata_offset: Optional[int],
    blockids_offset: Optional[int],
) -> bool:
    return (
        rowptr_offset is not None
        and colidx_offset is not None
        and blockdata_offset is not None
        and blockids_offset is not None
    )


def int_or_zero(val: Optional[Any]) -> int:
    return int(val) if val is not None else 0


def build_step_cfg(
    *,
    state: dict,
    global_bcsr_available: bool,
    global_bcsr_dir: str,
    neurons_per_core: int,
) -> dict:
    template = resolve_step_activation_template(
        template_override=str(state.get("STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE", "") or ""),
        global_bcsr_available=bool(global_bcsr_available),
        global_bcsr_dir=str(global_bcsr_dir),
    )

    can_load = step_bcsr_offsets_ready(
        rowptr_offset=state.get("STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"),
        colidx_offset=state.get("STEP_ACTIVATION_BCSR_COLIDX_OFFSET"),
        blockdata_offset=state.get("STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"),
        blockids_offset=state.get("STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"),
    )

    return {
        "random_activation_enable": int(state.get("STEP_RANDOM_ACT_ENABLE", 0)),
        "activation_period_cycles": int(state.get("STEP_ACTIVATION_PERIOD_CYCLES", 0)),
        "activation_fraction": float(state.get("STEP_ACTIVATION_FRACTION", 0.0)),
        "activation_fanout": int(state.get("STEP_ACTIVATION_FANOUT", 0)),
        "activation_seed": int(state.get("STEP_ACTIVATION_SEED", 0)),
        "activation_event_weight": float(state.get("STEP_ACTIVATION_EVENT_WEIGHT", 0.0)),
        "activation_trigger_core": int(state.get("STEP_ACTIVATION_TRIGGER_CORE", 0)),
        "activation_pre_pattern": str(state.get("STEP_ACTIVATION_PRE_PATTERN", "bernoulli") or "bernoulli").strip().lower(),
        "activation_pre_cluster_len": int(state.get("STEP_ACTIVATION_PRE_CLUSTER_LEN", 0) or 0),
        "activation_use_bcsr_routes": bool(state.get("STEP_ACTIVATION_USE_BCSR_ROUTES", 0)),
        "activation_template": template,
        "activation_bcsr_rows_per_core": int(neurons_per_core),
        "activation_bcsr_br": int(state.get("STEP_ACTIVATION_BCSR_BR", 16) or 16),
        "activation_bcsr_bc": int(state.get("STEP_ACTIVATION_BCSR_BC", 16) or 16),
        "activation_bcsr_idx_bytes": int(state.get("STEP_ACTIVATION_BCSR_IDX_BYTES", 2) or 2),
        "activation_bcsr_val_bytes": int(state.get("STEP_ACTIVATION_BCSR_VAL_BYTES", 4) or 4),
        "activation_bcsr_rowptr_offset": int_or_zero(state.get("STEP_ACTIVATION_BCSR_ROWPTR_OFFSET")),
        "activation_bcsr_colidx_offset": int_or_zero(state.get("STEP_ACTIVATION_BCSR_COLIDX_OFFSET")),
        "activation_bcsr_blockdata_offset": int_or_zero(state.get("STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET")),
        "activation_bcsr_blockids_offset": int_or_zero(state.get("STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET")),
        "activation_bcsr_can_load": bool(can_load),
        "activation_bcsr_weight_epsilon": float(state.get("STEP_ACTIVATION_BCSR_WEIGHT_EPS", 0.0)),
        "reset_mem_each_step": int(state.get("STEP_RESET_MEM_EACH_STEP", 0)),
    }
