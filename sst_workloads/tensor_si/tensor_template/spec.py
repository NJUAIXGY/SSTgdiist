from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from snndl_spec.common import as_bool as _as_bool
from snndl_spec.common import as_dict as _as_dict
from snndl_spec.common import as_int as _as_int
from snndl_spec.common import as_list as _as_list
from snndl_spec.common import as_str as _as_str
from snndl_spec.common import reject_unknown_keys as _reject_unknown_keys_common
from snndl_spec.component_roles import SUPPORTED_COMPONENT_ROLES as SUPPORTED_COMPONENT_ROLES_V3


class SpecError(ValueError):
    pass


def _resolve_repo_path(raw_path: str) -> str:
    """
    Resolve a user-provided path to an absolute path.

    Heuristic:
      1) If absolute (or ~), expand and return.
      2) If relative, try repo-root (preferred), then spec dir (spec-first),
         then current working directory, then tensor_si project root.
      3) If nothing exists, default to repo-root joined path for determinism.
    """

    s = str(raw_path or "").strip()
    if not s:
        return s
    p = Path(s).expanduser()
    if p.is_absolute():
        return str(p)

    # spec.py: <repo_root>/sst_workloads/tensor_si/tensor_template/spec.py
    repo_root = Path(__file__).resolve().parents[3]
    project_root = Path(__file__).resolve().parents[1]

    candidates: List[Path] = [repo_root]
    spec_path = os.environ.get("TENSOR_SPEC_JSON", "").strip()
    if spec_path:
        try:
            candidates.append(Path(spec_path).expanduser().resolve().parent)
        except Exception:
            pass
    candidates.extend([Path.cwd(), project_root])

    for base in candidates:
        cand = (base / p).resolve()
        if cand.exists():
            return str(cand)

    return str((repo_root / p).resolve())


_RAM2_DRAM_HEADER_RE = re.compile(r"^\s*DRAM\s*:\s*$", re.IGNORECASE)
_RAM2_IMPL_LINE_RE = re.compile(r"^\s*impl\s*:\s*([A-Za-z0-9_\\-]+)\s*$", re.IGNORECASE)


def _parse_ramulator2_cfg_dram_impl(cfg_text: str) -> str:
    """Best-effort parse of Ramulator2 YAML-like config to locate MemorySystem.DRAM.impl."""

    dram_indent: int | None = None
    for raw in str(cfg_text or "").splitlines():
        # Strip inline comments (Ramulator2 configs use '#' for comments).
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if dram_indent is None:
            if _RAM2_DRAM_HEADER_RE.match(line):
                dram_indent = len(line) - len(line.lstrip(" "))
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent <= dram_indent:
            # DRAM block ended.
            dram_indent = None
            if _RAM2_DRAM_HEADER_RE.match(line):
                dram_indent = len(line) - len(line.lstrip(" "))
            continue

        m = _RAM2_IMPL_LINE_RE.match(line)
        if m:
            return str(m.group(1) or "").strip()

    return ""


def _infer_dma_hbm_defaults_from_ram2_cfg(config_file_abs: str) -> tuple[int | None, int | None]:
    """Infer (tensor_dma_hbm_channels, tensor_dma_hbm_channel_interleave_bytes) from ramulator2 config."""

    path = Path(str(config_file_abs or "")).expanduser()
    if not path.exists():
        return (None, None)
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return (None, None)

    dram_impl = _parse_ramulator2_cfg_dram_impl(txt).strip().lower()
    if dram_impl == "hbm2":
        # Default to 4 MemControllers for HBM2 in our tensor mesh model (consistent with M24/M26 gates).
        return (4, 256)
    if dram_impl in {"ddr4", "ddr5"}:
        return (1, 256)
    return (None, None)


def load_spec(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SpecError(f"spec file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SpecError(f"failed to load spec json: {p}") from exc
    if not isinstance(raw, dict):
        raise SpecError("spec root must be an object")
    return raw


def _reject_unknown_keys(*, obj: Dict[str, Any], allowed: set[str], ctx: str, allow_unknown_fields: bool) -> None:
    _reject_unknown_keys_common(
        obj=obj,
        allowed=allowed,
        ctx=ctx,
        allow_unknown_fields=allow_unknown_fields,
        exc_type=SpecError,
    )


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_spec(raw: Dict[str, Any], defaults: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SpecError("spec input must be a dict")

    merged_raw = _deep_merge(defaults or {}, raw)

    schema_version = merged_raw.get("schema_version", 1)
    if schema_version not in (1, 3):
        raise SpecError(f"unsupported schema_version: {schema_version!r} (expected 1 or 3)")

    validate = _as_dict(merged_raw.get("validate"))
    allow_unknown_fields = _as_bool(validate.get("allow_unknown_fields"), False)

    allowed_spec_keys = {
        "model",
        "schema_version",
        "platform",
        "noc",
        "memory",
        "pe",
        "workload",
        "validate",
        "components",
        "overrides",
    }
    _reject_unknown_keys(obj=merged_raw, allowed=allowed_spec_keys, ctx="spec", allow_unknown_fields=allow_unknown_fields)

    platform = _as_dict(merged_raw.get("platform"))
    _reject_unknown_keys(
        obj=platform,
        allowed={"mesh_size", "node_limit", "stop", "exec_mode"},
        ctx="platform",
        allow_unknown_fields=allow_unknown_fields,
    )
    mesh_size = _as_int(platform.get("mesh_size"), 4)
    mesh_size = max(1, int(mesh_size))
    total_nodes = mesh_size * mesh_size
    node_limit = _as_int(platform.get("node_limit"), total_nodes)
    node_limit = max(1, min(int(node_limit), total_nodes))

    stop = _as_dict(platform.get("stop"))
    _reject_unknown_keys(
        obj=stop,
        allowed={"mode", "max_steps", "simulation_time"},
        ctx="platform.stop",
        allow_unknown_fields=allow_unknown_fields,
    )
    stop_mode = _as_str(stop.get("mode"), "").strip().lower()
    simulation_time = _as_str(stop.get("simulation_time"), "10us")
    if stop_mode == "step_limited":
        raise SpecError("tensor model does not support platform.stop.mode=step_limited (use mode=time)")

    pe = _as_dict(merged_raw.get("pe"))
    _reject_unknown_keys(
        obj=pe,
        allowed={"cores_per_pe", "num_cores_per_pe", "neurons_per_core"},
        ctx="pe",
        allow_unknown_fields=allow_unknown_fields,
    )
    cores_per_pe = _as_int(pe.get("cores_per_pe"), 0)
    if cores_per_pe <= 0:
        cores_per_pe = _as_int(pe.get("num_cores_per_pe"), 4)
    num_cores_per_pe = max(1, int(cores_per_pe))
    neurons_per_core = max(1, _as_int(pe.get("neurons_per_core"), 4))
    neurons_per_pe = num_cores_per_pe * neurons_per_core

    noc = _as_dict(merged_raw.get("noc"))
    _reject_unknown_keys(
        obj=noc,
        allowed={"type", "params"},
        ctx="noc",
        allow_unknown_fields=allow_unknown_fields,
    )
    noc_type = _as_str(noc.get("type"), "").strip().lower()
    if noc_type:
        if noc_type in ("merlin_mesh", "mesh", "merlin.mesh"):
            noc_type = "merlin_mesh"
        elif noc_type in ("merlin_torus", "torus", "merlin.torus"):
            noc_type = "merlin_torus"
        else:
            raise SpecError(f"invalid noc.type={noc_type!r} (expected merlin_mesh|merlin_torus)")
    noc_params = _as_dict(noc.get("params"))
    _reject_unknown_keys(
        obj=noc_params,
        allowed={"link_bw", "buffer_size", "num_vns", "shape", "width", "local_ports"},
        ctx="noc.params",
        allow_unknown_fields=allow_unknown_fields,
    )
    network_bandwidth = _as_str(noc_params.get("link_bw"), "40GiB/s")
    buffer_size = _as_str(noc_params.get("buffer_size"), "8KiB")
    network_num_vns = max(1, _as_int(noc_params.get("num_vns"), 2))

    def _parse_2d_shape(raw_shape: str, *, default_mesh_size: int) -> tuple[int, int]:
        s = str(raw_shape or "").strip().lower()
        if not s:
            return int(default_mesh_size), int(default_mesh_size)
        parts = [p.strip() for p in s.split("x") if p.strip()]
        if len(parts) != 2:
            raise SpecError(f"invalid noc.params.shape={raw_shape!r} (expected '<X>x<Y>')")
        try:
            dim_x = int(parts[0])
            dim_y = int(parts[1])
        except Exception as exc:
            raise SpecError(f"invalid noc.params.shape={raw_shape!r} (expected '<X>x<Y>' with integers)") from exc
        if dim_x <= 0 or dim_y <= 0:
            raise SpecError(f"invalid noc.params.shape={raw_shape!r} (expected '<X>x<Y>' with X,Y > 0)")
        return int(dim_x), int(dim_y)

    noc_shape_raw = _as_str(noc_params.get("shape"), "").strip()
    noc_dim_x, noc_dim_y = _parse_2d_shape(noc_shape_raw, default_mesh_size=int(mesh_size))
    noc_shape = f"{noc_dim_x}x{noc_dim_y}"
    if noc_dim_x * noc_dim_y != total_nodes:
        raise SpecError(
            f"invalid noc.params.shape={noc_shape!r} (expected X*Y == total_nodes={total_nodes})"
        )
    noc_width = _as_str(noc_params.get("width"), "1x1").strip().lower()
    if not noc_width:
        noc_width = "1x1"
    if noc_width != "1x1":
        raise SpecError(f"unsupported noc.params.width={noc_width!r} (expected '1x1' for now)")
    noc_local_ports = max(1, _as_int(noc_params.get("local_ports"), 1))
    if noc_local_ports != 1:
        raise SpecError(
            f"unsupported noc.params.local_ports={noc_local_ports!r} (expected 1 for now)"
        )

    memory = _as_dict(merged_raw.get("memory"))
    _reject_unknown_keys(
        obj=memory,
        allowed={"type", "backend", "params"},
        ctx="memory",
        allow_unknown_fields=allow_unknown_fields,
    )
    backend = _as_dict(memory.get("backend"))
    backend_type = "simple"
    backend_params: Dict[str, Any] = {}
    if backend:
        _reject_unknown_keys(
            obj=backend,
            allowed={"type", "params"},
            ctx="memory.backend",
            allow_unknown_fields=allow_unknown_fields,
        )
        backend_type = _as_str(backend.get("type"), "simple").strip().lower() or "simple"
        if backend_type in ("ram2", "ramulator2", "memhierarchy.ramulator2"):
            backend_type = "ramulator2"
        elif backend_type in ("simple", "simplemem", "memhierarchy.simplemem"):
            backend_type = "simple"
        else:
            raise SpecError(
                f"unsupported tensor memory.backend.type={backend_type!r} (expected 'simple' or 'ramulator2')"
            )

        backend_params = _as_dict(backend.get("params"))
        if backend_type == "ramulator2":
            _reject_unknown_keys(
                obj=backend_params,
                allowed={"configFile", "debug", "debug_level"},
                ctx="memory.backend.params",
                allow_unknown_fields=allow_unknown_fields,
            )
            cfg = _as_str(backend_params.get("configFile"), "").strip()
            if not cfg:
                raise SpecError("memory.backend.params.configFile is required when backend.type=ramulator2")
            backend_params["configFile"] = _resolve_repo_path(cfg)
        else:
            _reject_unknown_keys(
                obj=backend_params,
                allowed=set(),
                ctx="memory.backend.params",
                allow_unknown_fields=allow_unknown_fields,
            )

    mem_params = _as_dict(memory.get("params"))
    _reject_unknown_keys(
        obj=mem_params,
        allowed={"core_mem_region_bytes", "mem_access_time"},
        ctx="memory.params",
        allow_unknown_fields=allow_unknown_fields,
    )
    core_mem_region_bytes = max(1, _as_int(mem_params.get("core_mem_region_bytes"), 1 * 1024 * 1024))
    mem_access_time = _as_str(mem_params.get("mem_access_time"), "100ns")

    mesh_cfg: Dict[str, Any] = {
        "mesh_size": mesh_size,
        "total_nodes": total_nodes,
        "node_limit": node_limit,
        "num_cores_per_pe": num_cores_per_pe,
        "neurons_per_core": neurons_per_core,
        "neurons_per_pe": neurons_per_pe,
        "network_bandwidth": network_bandwidth,
        "buffer_size": buffer_size,
        "network_num_vns": network_num_vns,
        "noc_type": noc_type or "merlin_mesh",
        "noc_shape": noc_shape,
        "noc_width": noc_width,
        "noc_local_ports": int(noc_local_ports),
        "core_mem_region_bytes": core_mem_region_bytes,
        "pe_mem_region_bytes": core_mem_region_bytes * num_cores_per_pe,
        "mem_access_time": mem_access_time,
        "mem_backend": backend_type,
        "mem_backend_params": backend_params,
    }

    workload = _as_dict(merged_raw.get("workload"))
    allowed_workload_keys = (
        {"tensor"} if int(schema_version) == 1 else {"type", "stats_modules", "params", "tensor", "program"}
    )
    _reject_unknown_keys(
        obj=workload,
        allowed=allowed_workload_keys,
        ctx="workload",
        allow_unknown_fields=allow_unknown_fields,
    )
    wl_type = _as_str(workload.get("type"), "tensor").strip().lower() if int(schema_version) == 3 else "tensor"
    if wl_type and wl_type != "tensor":
        raise SpecError(f"invalid workload.type={wl_type!r} (expected 'tensor')")
    wl_stats_modules = _as_str(workload.get("stats_modules"), "").strip()
    if not wl_stats_modules:
        wl_stats_modules = "tensor"
    mesh_cfg["workload_stats_modules"] = wl_stats_modules

    tensor_cfg: Dict[str, Any] = {
        "workload_impl": "tensor",
        # M37+: capability/maturity metadata knobs (no functional behavior change by default).
        "tensor_capability_profile": "baseline_npu_like_v1",
        "tensor_scheduler_model": "legacy",
        "tensor_memory_hierarchy_profile": "baseline",
        # M68: RAS policy metadata/contract knob (current model keeps it as config evidence).
        "tensor_ras_policy": "none",
        "tensor_calibration_tag": "",
        "tensor_m": 256,
        "tensor_n": 256,
        "tensor_k": 256,
        "tensor_element_bytes": 2,
        "tensor_array_m": 32,
        "tensor_array_n": 32,
        "tensor_compute_efficiency": 1.0,
        "tensor_compute_precision": "fp16",
        "tensor_compute_profile_override_enable": 0,
        "tensor_compute_throughput_scale": 1.0,
        "tensor_compute_pipeline_latency_cycles": 0,
        "tensor_mxu_wavefront_enable": 0,
        "tensor_mxu_wavefront_alpha": 1.0,
        # M30+: MXU feed/drain bandwidth model (bytes/cycle). 0 = disabled (unlimited).
        "tensor_mxu_a_bytes_per_cycle": 0,
        "tensor_mxu_b_bytes_per_cycle": 0,
        "tensor_mxu_c_bytes_per_cycle": 0,
        "tensor_overlap_enable": 1,
        "tensor_start_cycle": 1,
        "tensor_iterations": 0,
        "tensor_mem_enable": 1,
        "tensor_mem_region_bytes": core_mem_region_bytes,
        "tensor_mem_req_bytes": 64,
        "tensor_mem_max_outstanding": 32,
        "tensor_mem_timing_model": "off",
        "tensor_mem_bank_groups_per_channel": 1,
        "tensor_mem_banks_per_group": 1,
        "tensor_mem_row_bytes": 8192,
        "tensor_mem_bank_queue_depth": 16,
        "tensor_mem_sched_policy": "fifo",
        "tensor_mem_t_rcd_cycles": 0,
        "tensor_mem_t_cl_cycles": 0,
        "tensor_mem_t_rp_cycles": 0,
        "tensor_mem_t_burst_cycles": 0,
        "tensor_mem_t_ccd_s_cycles": 0,
        "tensor_mem_t_ccd_l_cycles": 0,
        "tensor_mem_refresh_interval_cycles": 0,
        "tensor_mem_refresh_block_cycles": 0,
        "tensor_dataflow": "os",
        "tensor_tile_m": 0,
        "tensor_tile_n": 0,
        "tensor_tile_k": 0,
        "tensor_exec_mode": "bulk",
        "tensor_tile_schedule": "auto",
        "tensor_writeback_policy": "at_end_of_k",
        # Program mode (M6+): optional command stream (compiled to a DSL string).
        "tensor_program_dsl": "",
        "tensor_program_loop": 1,
        "tensor_program_issue_width": 4,
        "tensor_program_engine_priority": "dma>mxu>vec>coll",
        # M65: trace-v2 compiler metadata (for evidence/validation pipeline).
        "tensor_trace_v2_version": 0,
        "tensor_trace_v2_op_count": 0,
        "tensor_trace_v2_dependency_edges": 0,
        "tensor_trace_v2_resource_kinds": 0,
        # M75: trace-v3 compiler metadata (adds execution-window semantics).
        "tensor_trace_v3_version": 0,
        "tensor_trace_v3_op_count": 0,
        "tensor_trace_v3_dependency_edges": 0,
        "tensor_trace_v3_resource_kinds": 0,
        "tensor_trace_v3_tile_windows": 0,
        "tensor_trace_v3_barrier_count": 0,
        "tensor_trace_v3_resource_windows": 0,
        # M85: trace-v4 compiler metadata (adds phase-5 bridge evidence fields).
        "tensor_trace_v4_version": 0,
        "tensor_trace_v4_op_count": 0,
        "tensor_trace_v4_dependency_edges": 0,
        "tensor_trace_v4_resource_kinds": 0,
        "tensor_trace_v4_tile_windows": 0,
        "tensor_trace_v4_barrier_count": 0,
        "tensor_trace_v4_resource_windows": 0,
        # Program mode scratchpad modeling (M18+): number of logical UB buffers (e.g., ping-pong).
        "tensor_program_ub_buffers": 1,
        # Program mode DMA engine modeling (M20+): when enabled, allow 1 read + 1 write DMA op to overlap.
        "tensor_program_dma_dual_enable": 0,
        # Vector engine placeholder for softmax/eltwise in program mode.
        "tensor_vector_elems_per_cycle": 64,
        "tensor_vector_pipeline_latency_cycles": 0,
        "tensor_ub_bytes": 0,
        "tensor_weight_bytes": 0,
        "tensor_acc_bytes": 0,
        "tensor_onchip_model_enable": 0,
        "tensor_ub_bank_bytes": 0,
        "tensor_ub_read_ports": 0,
        "tensor_ub_write_ports": 0,
        "tensor_onchip_bank_model_enable": 0,
        "tensor_ub_bank_count": 1,
        "tensor_ub_bank_select_policy": "interleave",
        "tensor_ub_bank_conflict_mode": "queue",
        "tensor_acc_bank_bytes": 0,
        "tensor_acc_read_ports": 0,
        "tensor_acc_write_ports": 0,
        "tensor_acc_bank_count": 1,
        "tensor_acc_bank_select_policy": "interleave",
        "tensor_acc_bank_conflict_mode": "queue",
        "tensor_bank_queue_depth": 16,
        "tensor_spill_enable": 0,
        "tensor_spill_packet_bytes": 256,
        "tensor_spill_share_noc_budget": 1,
        "tensor_dma_bandwidth_bytes_per_cycle": 0,
        # M29+: DMA micro-architecture knobs (program-mode). Defaults preserve legacy behavior.
        "tensor_dma_burst_bytes": 0,
        "tensor_dma_setup_cycles": 0,
        "tensor_dma_read_engines": 1,
        "tensor_dma_write_engines": 1,
        "tensor_dma_max_inflight_per_engine": 0,
        "tensor_dma_shared_bandwidth_bytes_per_cycle": 0,
        "tensor_dma_hbm_channels": 1,
        "tensor_dma_hbm_channel_bandwidth_bytes_per_cycle": 0,
        "tensor_dma_hbm_channel_interleave_bytes": 256,
        "tensor_double_buffer": 0,
        "tensor_collective_type": "none",
        "tensor_collective_blocking": 0,
        "tensor_collective_scope": "per_core",
        "tensor_collective_bytes": 0,
        "tensor_collective_period_cycles": 0,
        "tensor_collective_pattern": "ring",
        "tensor_collective_packet_bytes": 256,
        "tensor_collective_algo": "legacy_bytes",
        "tensor_collective_chunk_bytes": 0,
        "tensor_collective_reduce_overhead_cycles": 0,
        "tensor_collective_max_inflight_chunks": 1,
        "tensor_collective_credit_enable": 0,
        "tensor_collective_credit_window_chunks": 0,
        "tensor_collective_credit_return_mode": "event_on_recv",
        "tensor_collective_backpressure_mode": "hard",
        "tensor_noc_bandwidth_bytes_per_cycle": 0,
        "tensor_collective_overlap_with_compute": 1,
        "tensor_collective_issue_priority": "control_first",
        # M8: 2D torus collective algorithm helpers (used when tensor_collective_algo=torus_2d_rs_ag).
        "tensor_collective_2d_dim_x": 0,
        "tensor_collective_2d_dim_y": 0,
        "tensor_collective_2d_row_major": 1,
        "tensor_comm_enable": 0,
        "tensor_comm_period_cycles": 0,
        "tensor_comm_payload_bytes": 0,
        "tensor_strict": 1,
        "tensor_seed": 0,
    }

    tensor_params_v1 = _as_dict(_as_dict(workload.get("tensor")).get("params"))
    tensor_params_v3 = _as_dict(workload.get("params")) if int(schema_version) == 3 else {}
    tensor_params = dict(tensor_params_v1)
    tensor_params.update(tensor_params_v3)

    # --- Backend-driven defaults (M34) ---
    # When using ramulator2 backend, infer a sensible default channel count/interleave for HBM-like configs.
    # Only apply when the user did NOT explicitly set these keys in workload.params.
    if backend_type == "ramulator2":
        cfg_file = _as_str(backend_params.get("configFile"), "").strip()
        ch_infer, interleave_infer = _infer_dma_hbm_defaults_from_ram2_cfg(cfg_file) if cfg_file else (None, None)
        if "tensor_dma_hbm_channels" not in tensor_params and ch_infer is not None:
            tensor_cfg["tensor_dma_hbm_channels"] = int(ch_infer)
        if "tensor_dma_hbm_channel_interleave_bytes" not in tensor_params and interleave_infer is not None:
            tensor_cfg["tensor_dma_hbm_channel_interleave_bytes"] = int(interleave_infer)

    # --- Aliases (M10) ---
    # Credit/window/inflight are packet-count based, but older keys use *_chunks naming.
    # Accept *_pkts as a clearer alias and fold into the canonical *_chunks keys.
    if "tensor_collective_max_inflight_pkts" in tensor_params:
        tensor_params["tensor_collective_max_inflight_chunks"] = tensor_params.get("tensor_collective_max_inflight_pkts")
        tensor_params.pop("tensor_collective_max_inflight_pkts", None)
    if "tensor_collective_credit_window_pkts" in tensor_params:
        tensor_params["tensor_collective_credit_window_chunks"] = tensor_params.get("tensor_collective_credit_window_pkts")
        tensor_params.pop("tensor_collective_credit_window_pkts", None)

    if not allow_unknown_fields:
        unknown_keys = [key for key in tensor_params if key not in tensor_cfg]
        if unknown_keys:
            raise SpecError(f"unknown tensor params: {', '.join(sorted(unknown_keys))}")
    tensor_cfg.update(tensor_params)
    if "tensor_mem_region_bytes" not in tensor_params:
        tensor_cfg["tensor_mem_region_bytes"] = core_mem_region_bytes

    # --- Program (schema_v3 only) ---
    # Keep the spec-side representation structured, but compile to a lightweight DSL
    # so C++ does not need a JSON parser.
    program_raw = workload.get("program") if int(schema_version) == 3 else None
    if program_raw is not None:
        if not isinstance(program_raw, dict):
            raise SpecError("workload.program must be an object")
        _reject_unknown_keys(
            obj=program_raw,
            allowed={"loop", "ops"},
            ctx="workload.program",
            allow_unknown_fields=allow_unknown_fields,
        )
        program_loop = _as_bool(program_raw.get("loop"), True)
        ops_raw = program_raw.get("ops")
        if not isinstance(ops_raw, list) or not ops_raw:
            raise SpecError("workload.program.ops must be a non-empty list")

        parts: List[str] = []
        has_m7_ops = False
        has_legacy_gemm = False
        ub_buffers = max(1, _as_int(tensor_cfg.get("tensor_program_ub_buffers"), 1))
        ub_bytes_total = max(0, _as_int(tensor_cfg.get("tensor_ub_bytes"), 0))
        addr_aware = False
        for op_raw in ops_raw:
            if not isinstance(op_raw, dict):
                continue
            if any(k in op_raw for k in ("ub_addr", "ub_read_addr", "ub_write_addr")):
                addr_aware = True
                break

        ub_part = 0
        if addr_aware:
            if ub_bytes_total <= 0:
                raise SpecError("address-aware program ops require tensor_ub_bytes > 0")
            if ub_bytes_total % ub_buffers != 0:
                raise SpecError(
                    "address-aware program ops require tensor_ub_bytes divisible by tensor_program_ub_buffers "
                    f"(got ub_bytes={ub_bytes_total}, ub_buffers={ub_buffers})"
                )
            ub_part = ub_bytes_total // ub_buffers
            if ub_part <= 0:
                raise SpecError("address-aware program ops require per-buffer ub partition > 0")

            # Validate region definitions for consistency (size + overlap).
            region_sizes: Dict[tuple[int, int], int] = {}
            for j, op_j in enumerate(ops_raw):
                if not isinstance(op_j, dict):
                    continue
                op_type_j = _as_str(op_j.get("op_type"), "").strip().lower()
                if not op_type_j:
                    continue
                if op_type_j not in {"gemm", "allreduce", "softmax", "dma_read", "dma_write", "fence", "gemm_ub"}:
                    continue

                buf_j = max(0, _as_int(op_j.get("buf"), 0))
                if buf_j >= ub_buffers:
                    raise SpecError(
                        f"workload.program.ops[{j}].buf={buf_j} out of range "
                        f"(expected 0..{ub_buffers - 1} by tensor_program_ub_buffers)"
                    )

                if op_type_j in {"dma_read", "dma_write"}:
                    if "ub_addr" not in op_j:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_addr is required for {op_type_j} in address-aware mode"
                        )
                    ub_addr_j = max(0, _as_int(op_j.get("ub_addr"), 0))
                    bytes_j = max(0, _as_int(op_j.get("bytes"), 0))
                    if bytes_j <= 0:
                        raise SpecError(f"workload.program.ops[{j}].bytes must be > 0 for {op_type_j}")
                    if ub_addr_j >= ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_addr={ub_addr_j} out of range "
                            f"(expected 0..{ub_part - 1} by ub partition)"
                        )
                    if ub_addr_j + bytes_j > ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_addr={ub_addr_j} with bytes={bytes_j} out of range "
                            f"(expected end <= {ub_part} by ub partition)"
                        )
                    key = (buf_j, ub_addr_j)
                    if key in region_sizes and region_sizes[key] != bytes_j:
                        raise SpecError(
                            f"address-aware region size mismatch for buf={buf_j} ub_addr={ub_addr_j} "
                            f"(expected {region_sizes[key]}, got {bytes_j})"
                        )
                    region_sizes[key] = bytes_j
                elif op_type_j == "gemm_ub":
                    if "ub_read_addr" not in op_j or "ub_write_addr" not in op_j:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_read_addr and ub_write_addr are required for gemm_ub in address-aware mode"
                        )
                    ub_r = max(0, _as_int(op_j.get("ub_read_addr"), 0))
                    ub_w = max(0, _as_int(op_j.get("ub_write_addr"), 0))
                    if ub_r >= ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_read_addr={ub_r} out of range "
                            f"(expected 0..{ub_part - 1} by ub partition)"
                        )
                    if ub_w >= ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_write_addr={ub_w} out of range "
                            f"(expected 0..{ub_part - 1} by ub partition)"
                        )

                    r_bytes = max(0, _as_int(op_j.get("ub_read_bytes"), 0))
                    w_bytes = max(0, _as_int(op_j.get("ub_write_bytes"), 0))
                    if r_bytes > 0 and ub_r + r_bytes > ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_read_addr={ub_r} with ub_read_bytes={r_bytes} out of range "
                            f"(expected end <= {ub_part} by ub partition)"
                        )
                    if w_bytes > 0 and ub_w + w_bytes > ub_part:
                        raise SpecError(
                            f"workload.program.ops[{j}].ub_write_addr={ub_w} with ub_write_bytes={w_bytes} out of range "
                            f"(expected end <= {ub_part} by ub partition)"
                        )

                    if r_bytes > 0:
                        key_r = (buf_j, ub_r)
                        if key_r in region_sizes and region_sizes[key_r] != r_bytes:
                            raise SpecError(
                                f"address-aware region size mismatch for buf={buf_j} ub_addr={ub_r} "
                                f"(expected {region_sizes[key_r]}, got {r_bytes})"
                            )
                        region_sizes[key_r] = r_bytes
                    if w_bytes > 0:
                        key_w = (buf_j, ub_w)
                        if key_w in region_sizes and region_sizes[key_w] != w_bytes:
                            raise SpecError(
                                f"address-aware region size mismatch for buf={buf_j} ub_addr={ub_w} "
                                f"(expected {region_sizes[key_w]}, got {w_bytes})"
                            )
                        region_sizes[key_w] = w_bytes

            for b in range(ub_buffers):
                regs = [(addr, sz) for (bb, addr), sz in region_sizes.items() if bb == b and sz > 0]
                regs.sort(key=lambda x: x[0])
                for idx in range(1, len(regs)):
                    prev_a, prev_sz = regs[idx - 1]
                    cur_a, cur_sz = regs[idx]
                    prev_end = prev_a + prev_sz
                    if cur_a < prev_end:
                        raise SpecError(
                            f"address-aware regions overlap for buf={b}: "
                            f"[{prev_a},{prev_end}) overlaps with [{cur_a},{cur_a + cur_sz})"
                        )
        for i, op_raw in enumerate(ops_raw):
            if not isinstance(op_raw, dict):
                raise SpecError(f"workload.program.ops[{i}] must be an object")
            _reject_unknown_keys(
                obj=op_raw,
                allowed={
                    "op_type",
                    "bytes",
                    "elems",
                    "blocking",
                    "cycles",
                    "ub_read_bytes",
                    "ub_write_bytes",
                    # M18+: UB buffer selection + reuse semantics.
                    "buf",
                    "reset",
                    "consume",
                    # M22+: address-aware UB regions for program ops.
                    "ub_addr",
                    "ub_read_addr",
                    "ub_write_addr",
                    # M21+: auto-cycle estimation requires explicit GEMM shape.
                    "m",
                    "n",
                    "k",
                },
                ctx=f"workload.program.ops[{i}]",
                allow_unknown_fields=allow_unknown_fields,
            )
            op_type = _as_str(op_raw.get("op_type"), "").strip().lower()
            if not op_type:
                raise SpecError(f"workload.program.ops[{i}].op_type is required")
            if op_type not in {"gemm", "allreduce", "softmax", "dma_read", "dma_write", "fence", "gemm_ub"}:
                raise SpecError(
                    f"workload.program.ops[{i}].op_type={op_type!r} "
                    "(expected gemm|allreduce|softmax|dma_read|dma_write|fence|gemm_ub)"
                )

            kv: List[str] = []
            if op_type == "gemm":
                has_legacy_gemm = True
            elif op_type in {"dma_read", "dma_write", "fence", "gemm_ub"}:
                has_m7_ops = True

            buf = max(0, _as_int(op_raw.get("buf"), 0))
            if buf >= ub_buffers:
                raise SpecError(
                    f"workload.program.ops[{i}].buf={buf} out of range "
                    f"(expected 0..{ub_buffers - 1} by tensor_program_ub_buffers)"
                )

            if op_type == "allreduce":
                bytes_val = max(0, _as_int(op_raw.get("bytes"), 0))
                if bytes_val > 0:
                    kv.append(f"bytes={bytes_val}")
                blocking = _as_bool(op_raw.get("blocking"), True)
                kv.append(f"blocking={1 if blocking else 0}")
            elif op_type == "softmax":
                elems = max(0, _as_int(op_raw.get("elems"), 0))
                if elems <= 0:
                    raise SpecError(f"workload.program.ops[{i}].elems must be > 0 for softmax")
                kv.append(f"elems={elems}")
            elif op_type in {"dma_read", "dma_write"}:
                bytes_val = max(0, _as_int(op_raw.get("bytes"), 0))
                if bytes_val <= 0:
                    raise SpecError(f"workload.program.ops[{i}].bytes must be > 0 for {op_type}")
                kv.append(f"bytes={bytes_val}")
                if buf:
                    kv.append(f"buf={buf}")
                if op_type == "dma_read":
                    reset = _as_bool(op_raw.get("reset"), False)
                    if reset:
                        kv.append("reset=1")
                else:
                    if "consume" in op_raw:
                        consume = _as_bool(op_raw.get("consume"), True)
                        kv.append(f"consume={1 if consume else 0}")
                if addr_aware:
                    ub_addr = max(0, _as_int(op_raw.get("ub_addr"), 0))
                    kv.append(f"ub_addr={ub_addr}")
            elif op_type == "gemm_ub":
                cycles = max(0, _as_int(op_raw.get("cycles"), 0))
                kv.append(f"cycles={cycles}")
                ub_read = max(0, _as_int(op_raw.get("ub_read_bytes"), 0))
                ub_write = max(0, _as_int(op_raw.get("ub_write_bytes"), 0))
                kv.append(f"ub_read={ub_read}")
                kv.append(f"ub_write={ub_write}")
                if buf:
                    kv.append(f"buf={buf}")
                if cycles == 0:
                    m_val = max(0, _as_int(op_raw.get("m"), 0))
                    n_val = max(0, _as_int(op_raw.get("n"), 0))
                    k_val = max(0, _as_int(op_raw.get("k"), 0))
                    if m_val <= 0 or n_val <= 0 or k_val <= 0:
                        raise SpecError(f"workload.program.ops[{i}] cycles=0 requires m,n,k > 0 for gemm_ub")
                    kv.append(f"m={m_val}")
                    kv.append(f"n={n_val}")
                    kv.append(f"k={k_val}")
                if addr_aware:
                    ub_r = max(0, _as_int(op_raw.get("ub_read_addr"), 0))
                    ub_w = max(0, _as_int(op_raw.get("ub_write_addr"), 0))
                    kv.append(f"ub_read_addr={ub_r}")
                    kv.append(f"ub_write_addr={ub_w}")

            token = op_type
            if kv:
                token = token + ":" + ",".join(kv)
            parts.append(token)

        if has_m7_ops and has_legacy_gemm:
            raise SpecError("workload.program cannot mix legacy 'gemm' with explicit dma/fence/gemm_ub ops")

        tensor_cfg["tensor_program_dsl"] = ";".join(parts)
        tensor_cfg["tensor_program_loop"] = 1 if program_loop else 0
        tensor_cfg["tensor_exec_mode"] = "program"
        if any(p.startswith("allreduce") for p in parts):
            ctype = str(tensor_cfg.get("tensor_collective_type", "") or "").strip().lower()
            if not ctype or ctype == "none":
                tensor_cfg["tensor_collective_type"] = "allreduce"

    precision = _as_str(tensor_cfg.get("tensor_compute_precision"), "fp16").strip().lower()
    if precision not in {"fp16", "bf16", "fp32", "tf32", "int8", "fp8"}:
        raise SpecError(
            f"invalid tensor_compute_precision={precision!r} (expected fp16|bf16|fp32|tf32|int8|fp8)"
        )
    tensor_cfg["tensor_compute_precision"] = precision

    exec_mode = _as_str(tensor_cfg.get("tensor_exec_mode"), "bulk").strip().lower()
    if exec_mode not in {"bulk", "tile", "program"}:
        raise SpecError(f"invalid tensor_exec_mode={exec_mode!r} (expected bulk|tile|program)")
    tensor_cfg["tensor_exec_mode"] = exec_mode
    if exec_mode == "program":
        dsl = _as_str(tensor_cfg.get("tensor_program_dsl"), "").strip()
        if not dsl:
            raise SpecError("tensor_exec_mode=program requires tensor_program_dsl (or workload.program)")
        tensor_cfg["tensor_program_loop"] = 1 if _as_bool(tensor_cfg.get("tensor_program_loop"), True) else 0
        tensor_cfg["tensor_program_issue_width"] = max(
            1, _as_int(tensor_cfg.get("tensor_program_issue_width"), 4)
        )
        tensor_cfg["tensor_program_ub_buffers"] = max(
            1, _as_int(tensor_cfg.get("tensor_program_ub_buffers"), 1)
        )
        tensor_cfg["tensor_vector_elems_per_cycle"] = max(
            1, _as_int(tensor_cfg.get("tensor_vector_elems_per_cycle"), 64)
        )
        tensor_cfg["tensor_vector_pipeline_latency_cycles"] = max(
            0, _as_int(tensor_cfg.get("tensor_vector_pipeline_latency_cycles"), 0)
        )
    tensor_cfg["tensor_compute_profile_override_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_compute_profile_override_enable"), False
    ) else 0
    tensor_cfg["tensor_onchip_model_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_onchip_model_enable"), False
    ) else 0
    tensor_cfg["tensor_onchip_bank_model_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_onchip_bank_model_enable"), False
    ) else 0
    tensor_cfg["tensor_spill_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_spill_enable"), False
    ) else 0
    tensor_cfg["tensor_spill_share_noc_budget"] = 1 if _as_bool(
        tensor_cfg.get("tensor_spill_share_noc_budget"), True
    ) else 0
    tensor_cfg["tensor_collective_overlap_with_compute"] = 1 if _as_bool(
        tensor_cfg.get("tensor_collective_overlap_with_compute"), True
    ) else 0
    try:
        throughput_scale = float(tensor_cfg.get("tensor_compute_throughput_scale", 1.0))
    except Exception as exc:
        raise SpecError("invalid tensor_compute_throughput_scale (expected number)") from exc
    if throughput_scale <= 0.0:
        raise SpecError("tensor_compute_throughput_scale must be > 0")
    tensor_cfg["tensor_compute_throughput_scale"] = throughput_scale
    tensor_cfg["tensor_compute_pipeline_latency_cycles"] = max(
        0, _as_int(tensor_cfg.get("tensor_compute_pipeline_latency_cycles"), 0)
    )
    tensor_cfg["tensor_mxu_a_bytes_per_cycle"] = max(0, _as_int(tensor_cfg.get("tensor_mxu_a_bytes_per_cycle"), 0))
    tensor_cfg["tensor_mxu_b_bytes_per_cycle"] = max(0, _as_int(tensor_cfg.get("tensor_mxu_b_bytes_per_cycle"), 0))
    tensor_cfg["tensor_mxu_c_bytes_per_cycle"] = max(0, _as_int(tensor_cfg.get("tensor_mxu_c_bytes_per_cycle"), 0))
    tensor_cfg["tensor_mxu_wavefront_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_mxu_wavefront_enable"), False
    ) else 0
    try:
        wf_alpha = float(tensor_cfg.get("tensor_mxu_wavefront_alpha", 1.0))
    except Exception as exc:
        raise SpecError("invalid tensor_mxu_wavefront_alpha (expected number)") from exc
    if wf_alpha < 0.0:
        raise SpecError("tensor_mxu_wavefront_alpha must be >= 0")
    tensor_cfg["tensor_mxu_wavefront_alpha"] = wf_alpha
    tensor_cfg["tensor_ub_bank_bytes"] = max(0, _as_int(tensor_cfg.get("tensor_ub_bank_bytes"), 0))
    tensor_cfg["tensor_acc_bank_bytes"] = max(0, _as_int(tensor_cfg.get("tensor_acc_bank_bytes"), 0))
    tensor_cfg["tensor_ub_bank_count"] = max(1, _as_int(tensor_cfg.get("tensor_ub_bank_count"), 1))
    tensor_cfg["tensor_acc_bank_count"] = max(1, _as_int(tensor_cfg.get("tensor_acc_bank_count"), 1))
    tensor_cfg["tensor_bank_queue_depth"] = max(1, _as_int(tensor_cfg.get("tensor_bank_queue_depth"), 16))
    tensor_cfg["tensor_ub_read_ports"] = max(0, _as_int(tensor_cfg.get("tensor_ub_read_ports"), 0))
    tensor_cfg["tensor_ub_write_ports"] = max(0, _as_int(tensor_cfg.get("tensor_ub_write_ports"), 0))
    tensor_cfg["tensor_acc_read_ports"] = max(0, _as_int(tensor_cfg.get("tensor_acc_read_ports"), 0))
    tensor_cfg["tensor_acc_write_ports"] = max(0, _as_int(tensor_cfg.get("tensor_acc_write_ports"), 0))
    tensor_cfg["tensor_spill_packet_bytes"] = max(8, _as_int(tensor_cfg.get("tensor_spill_packet_bytes"), 256))
    tensor_cfg["tensor_dma_burst_bytes"] = max(0, _as_int(tensor_cfg.get("tensor_dma_burst_bytes"), 0))
    tensor_cfg["tensor_dma_setup_cycles"] = max(0, _as_int(tensor_cfg.get("tensor_dma_setup_cycles"), 0))
    tensor_cfg["tensor_dma_read_engines"] = max(1, _as_int(tensor_cfg.get("tensor_dma_read_engines"), 1))
    tensor_cfg["tensor_dma_write_engines"] = max(1, _as_int(tensor_cfg.get("tensor_dma_write_engines"), 1))
    tensor_cfg["tensor_dma_max_inflight_per_engine"] = max(0, _as_int(tensor_cfg.get("tensor_dma_max_inflight_per_engine"), 0))
    tensor_cfg["tensor_trace_v2_version"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v2_version"), 0))
    tensor_cfg["tensor_trace_v2_op_count"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v2_op_count"), 0))
    tensor_cfg["tensor_trace_v2_dependency_edges"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v2_dependency_edges"), 0)
    )
    tensor_cfg["tensor_trace_v2_resource_kinds"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v2_resource_kinds"), 0)
    )
    tensor_cfg["tensor_trace_v3_version"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v3_version"), 0))
    tensor_cfg["tensor_trace_v3_op_count"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v3_op_count"), 0))
    tensor_cfg["tensor_trace_v3_dependency_edges"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v3_dependency_edges"), 0)
    )
    tensor_cfg["tensor_trace_v3_resource_kinds"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v3_resource_kinds"), 0)
    )
    tensor_cfg["tensor_trace_v3_tile_windows"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v3_tile_windows"), 0)
    )
    tensor_cfg["tensor_trace_v3_barrier_count"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v3_barrier_count"), 0)
    )
    tensor_cfg["tensor_trace_v3_resource_windows"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v3_resource_windows"), 0)
    )
    tensor_cfg["tensor_trace_v4_version"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v4_version"), 0))
    tensor_cfg["tensor_trace_v4_op_count"] = max(0, _as_int(tensor_cfg.get("tensor_trace_v4_op_count"), 0))
    tensor_cfg["tensor_trace_v4_dependency_edges"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v4_dependency_edges"), 0)
    )
    tensor_cfg["tensor_trace_v4_resource_kinds"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v4_resource_kinds"), 0)
    )
    tensor_cfg["tensor_trace_v4_tile_windows"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v4_tile_windows"), 0)
    )
    tensor_cfg["tensor_trace_v4_barrier_count"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v4_barrier_count"), 0)
    )
    tensor_cfg["tensor_trace_v4_resource_windows"] = max(
        0, _as_int(tensor_cfg.get("tensor_trace_v4_resource_windows"), 0)
    )
    tensor_cfg["tensor_collective_chunk_bytes"] = max(0, _as_int(tensor_cfg.get("tensor_collective_chunk_bytes"), 0))
    tensor_cfg["tensor_collective_reduce_overhead_cycles"] = max(
        0, _as_int(tensor_cfg.get("tensor_collective_reduce_overhead_cycles"), 0)
    )
    tensor_cfg["tensor_collective_max_inflight_chunks"] = max(
        1, _as_int(tensor_cfg.get("tensor_collective_max_inflight_chunks"), 1)
    )
    tensor_cfg["tensor_collective_credit_enable"] = 1 if _as_bool(
        tensor_cfg.get("tensor_collective_credit_enable"), False
    ) else 0
    tensor_cfg["tensor_collective_credit_window_chunks"] = max(
        0, _as_int(tensor_cfg.get("tensor_collective_credit_window_chunks"), 0)
    )
    credit_return_mode = _as_str(
        tensor_cfg.get("tensor_collective_credit_return_mode"),
        "event_on_recv",
    ).strip().lower()
    if credit_return_mode not in {"event_on_recv", "legacy_tick"}:
        raise SpecError(
            f"invalid tensor_collective_credit_return_mode={credit_return_mode!r} "
            "(expected event_on_recv|legacy_tick)"
        )
    tensor_cfg["tensor_collective_credit_return_mode"] = credit_return_mode
    tensor_cfg["tensor_noc_bandwidth_bytes_per_cycle"] = max(
        0, _as_int(tensor_cfg.get("tensor_noc_bandwidth_bytes_per_cycle"), 0)
    )
    collective_algo = _as_str(
        tensor_cfg.get("tensor_collective_algo"),
        "legacy_bytes",
    ).strip().lower()
    if collective_algo not in {"legacy_bytes", "ring_chunked", "torus_2d_rs_ag"}:
        raise SpecError(
            f"invalid tensor_collective_algo={collective_algo!r} "
            "(expected legacy_bytes|ring_chunked|torus_2d_rs_ag)"
        )
    tensor_cfg["tensor_collective_algo"] = collective_algo
    if collective_algo == "torus_2d_rs_ag":
        if (noc_type or "merlin_mesh") != "merlin_torus":
            raise SpecError("tensor_collective_algo=torus_2d_rs_ag requires noc.type=merlin_torus")

        dim_x = max(0, _as_int(tensor_cfg.get("tensor_collective_2d_dim_x"), 0))
        dim_y = max(0, _as_int(tensor_cfg.get("tensor_collective_2d_dim_y"), 0))
        if dim_x == 0 and dim_y == 0:
            dim_x, dim_y = int(noc_dim_x), int(noc_dim_y)
        elif dim_x == 0 or dim_y == 0:
            raise SpecError(
                "tensor_collective_algo=torus_2d_rs_ag requires tensor_collective_2d_dim_x and "
                "tensor_collective_2d_dim_y to be both set (or both 0 to infer from noc.params.shape)"
            )
        if int(dim_x) != int(noc_dim_x) or int(dim_y) != int(noc_dim_y):
            raise SpecError(
                "tensor_collective_algo=torus_2d_rs_ag requires tensor_collective_2d_dim_x/y "
                "to match noc.params.shape"
            )
        tensor_cfg["tensor_collective_2d_dim_x"] = int(dim_x)
        tensor_cfg["tensor_collective_2d_dim_y"] = int(dim_y)
        tensor_cfg["tensor_collective_2d_row_major"] = 1 if _as_bool(
            tensor_cfg.get("tensor_collective_2d_row_major"), True
        ) else 0
    ub_select_policy = _as_str(
        tensor_cfg.get("tensor_ub_bank_select_policy"),
        "interleave",
    ).strip().lower()
    if ub_select_policy not in {"interleave", "rr", "hash"}:
        raise SpecError(
            f"invalid tensor_ub_bank_select_policy={ub_select_policy!r} "
            "(expected interleave|rr|hash)"
        )
    tensor_cfg["tensor_ub_bank_select_policy"] = ub_select_policy
    acc_select_policy = _as_str(
        tensor_cfg.get("tensor_acc_bank_select_policy"),
        "interleave",
    ).strip().lower()
    if acc_select_policy not in {"interleave", "rr", "hash"}:
        raise SpecError(
            f"invalid tensor_acc_bank_select_policy={acc_select_policy!r} "
            "(expected interleave|rr|hash)"
        )
    tensor_cfg["tensor_acc_bank_select_policy"] = acc_select_policy
    ub_conflict_mode = _as_str(
        tensor_cfg.get("tensor_ub_bank_conflict_mode"),
        "queue",
    ).strip().lower()
    if ub_conflict_mode not in {"queue", "block"}:
        raise SpecError(
            f"invalid tensor_ub_bank_conflict_mode={ub_conflict_mode!r} "
            "(expected queue|block)"
        )
    tensor_cfg["tensor_ub_bank_conflict_mode"] = ub_conflict_mode
    acc_conflict_mode = _as_str(
        tensor_cfg.get("tensor_acc_bank_conflict_mode"),
        "queue",
    ).strip().lower()
    if acc_conflict_mode not in {"queue", "block"}:
        raise SpecError(
            f"invalid tensor_acc_bank_conflict_mode={acc_conflict_mode!r} "
            "(expected queue|block)"
        )
    tensor_cfg["tensor_acc_bank_conflict_mode"] = acc_conflict_mode
    backpressure_mode = _as_str(
        tensor_cfg.get("tensor_collective_backpressure_mode"),
        "hard",
    ).strip().lower()
    if backpressure_mode not in {"hard", "soft"}:
        raise SpecError(
            f"invalid tensor_collective_backpressure_mode={backpressure_mode!r} "
            "(expected hard|soft)"
        )
    tensor_cfg["tensor_collective_backpressure_mode"] = backpressure_mode
    issue_priority = _as_str(
        tensor_cfg.get("tensor_collective_issue_priority"),
        "control_first",
    ).strip().lower()
    if issue_priority not in {"control_first", "payload_first"}:
        raise SpecError(
            f"invalid tensor_collective_issue_priority={issue_priority!r} "
            "(expected control_first|payload_first)"
        )
    tensor_cfg["tensor_collective_issue_priority"] = issue_priority

    overrides: List[Dict[str, Any]] = []
    explicit_overrides = merged_raw.get("overrides")
    if explicit_overrides is not None and not isinstance(explicit_overrides, list):
        raise SpecError("overrides must be a list")
    overrides = [dict(x) for x in _as_list(explicit_overrides)]

    if int(schema_version) == 3:
        components = merged_raw.get("components")
        if components is None:
            components = {}
        if not isinstance(components, dict):
            raise SpecError("components must be an object (role -> params)")
        component_rules: List[Dict[str, Any]] = []
        for role in sorted(components.keys()):
            params = components.get(role)
            if not isinstance(role, str) or not role.strip():
                raise SpecError(f"invalid components role={role!r} (expected non-empty string)")
            role = role.strip()
            if (role not in SUPPORTED_COMPONENT_ROLES_V3) and (not allow_unknown_fields):
                raise SpecError(f"unknown components role={role!r} (supported: {sorted(SUPPORTED_COMPONENT_ROLES_V3)})")
            if params is None:
                continue
            if not isinstance(params, dict):
                raise SpecError(f"invalid components[{role!r}] (expected params object)")
            bad_values = []
            for k, v in params.items():
                if v is None or isinstance(v, (str, int, float, bool)):
                    continue
                bad_values.append(k)
            if bad_values:
                raise SpecError(
                    f"invalid components[{role!r}] param values for keys {sorted(bad_values)!r} "
                    "(expected scalar JSON values: string/number/bool/null)"
                )
            component_rules.append({"match": {"role": role}, "params": dict(params)})
        overrides = component_rules + overrides

    return {
        "raw": merged_raw,
        "runtime": {
            "mesh_size": mesh_size,
            "node_limit": node_limit,
            "simulation_time": simulation_time,
        },
        "mesh_cfg": mesh_cfg,
        "tensor_cfg": tensor_cfg,
        "overrides": overrides,
    }
