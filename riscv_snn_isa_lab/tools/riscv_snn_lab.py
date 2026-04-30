#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from riscv_snn_isa_lab.tools import export_riscv_snn_abi
from riscv_snn_isa_lab.tools import export_riscv_snn_control_plane_contract
from riscv_snn_isa_lab.tools import export_riscv_snn_research_report
from riscv_snn_isa_lab.tools import riscv_hart_ref
from riscv_snn_isa_lab.tools import supplementary_surface_contract
from riscv_snn_isa_lab.architecture_model import (
    ProgramEvidenceModel,
    ProgramProfileModel,
    runtime_summary_from_program_request,
)
from riscv_snn_isa_lab.architecture_model.model_types import (
    ReferenceProgramRequest,
    ReferenceProgramStep,
)
from riscv_snn_isa_lab.architecture_model.runtime_compare import (
    compare_reference_program_to_runtime,
    compare_reference_to_runtime,
)
from riscv_snn_isa_lab.architecture_model.reference_machine import ReferenceMachine

SNNDL_ROOT = REPO_ROOT / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL"
SST_DRAM_SI_ROOT = REPO_ROOT / "sst_dram_si"
GENERATOR_SCRIPT = SST_DRAM_SI_ROOT / "tools" / "generate_riscv_snn_firmware.py"
SPEC_CLI = SST_DRAM_SI_ROOT / "tools" / "mesh_spec_cli.py"
SMOKE_SCRIPT = SST_DRAM_SI_ROOT / "tools" / "run_mesh_with_time.sh"
MAINLINE_GATE_AUTHORITY_PATH = LAB_ROOT / "spec_authority" / "riscv_snn_mainline_gate_v1.json"
RUNTIME_GATE_AUTHORITY_PATH = LAB_ROOT / "spec_authority" / "riscv_snn_runtime_gate_v1.json"
ACCEL_AUTHORITY_PATH = LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.json"
ARCHITECTURE_MODEL_AUTHORITY_PATH = LAB_ROOT / "spec_authority" / "riscv_snn_architecture_model_v1.json"
SUPPLEMENTARY_SURFACE_AUTHORITY_PATH = (
    LAB_ROOT / "spec_authority" / "riscv_snn_supplementary_surface_v1.json"
)
BUILD_FRESHNESS_CONTRACTS: dict[tuple[str, str], dict[str, Any]] = {
    ("riscv_snn", "runtime_bridge"): {
        "contract_key": "riscv_snn.runtime_bridge.runtime_consumers",
        "contract_version": 1,
        "dependency_relpaths": (
            Path("services/synapse/weights/WeightMemorySubsystem.h"),
            Path("services/memory/sram_sim/model/BankedSramModel.h"),
        ),
        "required_target_relpaths": (
            Path("services/workload/snn/.libs/SnnWorkload.o"),
            Path("control/.libs/SnnPESubComponent.o"),
            Path("control/.libs/SnnPEOrchestrators.o"),
            Path("control/.libs/SnnPESubComponent_spike.o"),
            Path("control/.libs/SnnPESubComponent_bcsr.o"),
            Path("services/synapse/stdmem/.libs/SnnPESubComponent_mem.o"),
            Path("services/synapse/weights/.libs/WeightMemorySubsystem.o"),
            Path("services/memory/sram_sim/model/.libs/BankedSramModel.o"),
            Path(".libs/libSnnDL.so"),
        ),
        "rebuild_targets": (
            ("services/workload/snn/SnnWorkload.cc", "services/workload/snn/SnnWorkload.lo"),
            ("control/SnnPESubComponent.cc", "control/SnnPESubComponent.lo"),
            ("control/SnnPEOrchestrators.cc", "control/SnnPEOrchestrators.lo"),
            ("control/SnnPESubComponent_spike.cc", "control/SnnPESubComponent_spike.lo"),
            ("control/SnnPESubComponent_bcsr.cc", "control/SnnPESubComponent_bcsr.lo"),
            ("services/synapse/stdmem/SnnPESubComponent_mem.cc", "services/synapse/stdmem/SnnPESubComponent_mem.lo"),
            ("services/synapse/weights/WeightMemorySubsystem.cc", "services/synapse/weights/WeightMemorySubsystem.lo"),
            ("services/memory/sram_sim/model/BankedSramModel.cc", "services/memory/sram_sim/model/BankedSramModel.lo"),
        ),
    },
}
OPTIONAL_ADMISSION_PRIMARY_CONTRACT = "group_optional_admission_v1"
OPTIONAL_ADMISSION_PRIMARY_FIELDS = (
    "group_equivalence_path",
    "group_equivalence_all_ok",
    "group_history_path",
    "group_history_available",
    "group_history_entry_count",
    "group_history_all_dates_ok",
)
QUEUE_OPTIONAL_ADMISSION_ALIAS_FIELDS = (
    "queue_equivalence_path",
    "queue_equivalence_all_ok",
    "queue_history_path",
    "queue_history_available",
    "queue_history_entry_count",
    "queue_history_all_dates_ok",
)
OPTIONAL_PROMOTION_DOSSIER_PRIMARY_CONTRACT = "group_optional_promotion_dossier_v1"

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class SmokeFailure(RuntimeError):
    def __init__(self,
                 *,
                 spec_path: Path,
                 proc: subprocess.CompletedProcess[str],
                 message: str,
                 run_dir: Path | None = None) -> None:
        super().__init__(message)
        self.spec_path = spec_path
        self.proc = proc
        self.run_dir = run_dir
        self.output = f"{proc.stdout}{proc.stderr}".strip()
        self.returncode = proc.returncode


class PreflightFailure(RuntimeError):
    def __init__(self,
                 *,
                 spec_path: Path,
                 summary: dict[str, Any],
                 message: str,
                 returncode: int = 2) -> None:
        super().__init__(message)
        self.spec_path = spec_path
        self.summary = dict(summary)
        self.proc = subprocess.CompletedProcess([], returncode, stdout="", stderr=message)
        self.run_dir = None
        self.output = message
        self.returncode = returncode

REFERENCE_REGRESSION_PROGRAMS = [
    "external_dyn_desc_ref",
    "external_dyn_desc_fault_ref",
    "external_dyn_desc_bad_policy_ref",
    "external_dyn_desc_fault_rearm_ref",
    "external_dyn_desc_fault_overwrite_chain_ref",
    "barrier_wfi_order_ref",
]
PROGRAM_GROUPS = {
    "builder": REFERENCE_REGRESSION_PROGRAMS,
    "toolchain": [f"{program}_toolchain" for program in REFERENCE_REGRESSION_PROGRAMS],
}
SIDECAR_GATE_NAME = "riscv_snn_experimental_nightly"
SIDECAR_GATE_VERSION = "1.1"
ARTIFACT_SCHEMA_VERSION = 2
ARTIFACT_ROLE_DATED_NIGHTLY_INDEX = "dated_nightly_index"
ARTIFACT_ROLE_STABLE_HISTORY_ROLLUP = "stable_history_rollup"
ARTIFACT_ROLE_DATED_EQUIV_MATRIX = "dated_equivalence_matrix"
ARTIFACT_ROLE_DATED_ABI_AUDIT = "dated_abi_authority_audit"
ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE = "stable_top_level_gate"
ARTIFACT_ROLE_STABLE_ARTIFACT_ISOLATION_CHECK = "stable_artifact_isolation_check"
ARTIFACT_ROLE_STABLE_FULL_EQUIVALENCE_HISTORY = "stable_full_equivalence_history"
ARTIFACT_ROLE_STABLE_OPTIONAL_EQUIVALENCE_HISTORY = "stable_optional_equivalence_history"
ARTIFACT_ROLE_STABLE_ARTIFACT_ISOLATION_HISTORY = "stable_artifact_isolation_history"
ARTIFACT_ROLE_STABLE_OBSERVER_FULL_EQUIVALENCE_HISTORY = "stable_observer_full_equivalence_history"
ARTIFACT_ROLE_STABLE_SIDECAR_OBSERVER_SUMMARY = "stable_sidecar_observer_summary"
ARTIFACT_ROLE_STABLE_SURFACE_REFRESH_AUDIT = "stable_surface_refresh_audit"
ARTIFACT_ROLE_STABLE_SUPPLEMENTARY_SURFACE_HISTORY = "stable_supplementary_surface_history"
ARTIFACT_ROLE_OBSERVER_FAIL_RECOVERY_LOOP = "observer_fail_recovery_loop_summary"
ARTIFACT_ROLE_DATED_FAMILY_ASSET_AUDIT = "dated_family_asset_audit"
ARTIFACT_ROLE_DATED_FAMILY_ADMISSION_AUDIT = "dated_family_admission_audit"
ARTIFACT_ROLE_DATED_OPTIONAL_GROUP_REVIEW = "dated_optional_group_review"
ARTIFACT_ROLE_OPTIONAL_PROMOTION_DOSSIER = "optional_promotion_dossier"
ARTIFACT_ROLE_DATED_FAMILY_LANE_EQUIVALENCE = "dated_family_lane_equivalence"
ARTIFACT_ROLE_DATED_FAMILY_LANE_MATRIX = "dated_family_lane_matrix"
EQUIV_FAMILY_SPECS = {
    "external_dyn_desc_ref": {
        "snn_baseline": "external_dyn_desc_ref_snn_baseline.json",
        "runtime_bridge": "external_dyn_desc_ref_runtime_bridge.json",
    },
    "external_dyn_desc_fault_ref": {
        "snn_baseline": "external_dyn_desc_fault_ref_snn_baseline.json",
        "runtime_bridge": "external_dyn_desc_fault_ref_runtime_bridge.json",
    },
    "external_dyn_desc_bad_policy_ref": {
        "snn_baseline": "external_dyn_desc_bad_policy_ref_snn_baseline.json",
        "runtime_bridge": "external_dyn_desc_bad_policy_ref_runtime_bridge.json",
    },
    "external_dyn_desc_fault_rearm_ref": {
        "snn_baseline": "external_dyn_desc_fault_rearm_ref_snn_baseline.json",
        "runtime_bridge": "external_dyn_desc_fault_rearm_ref_runtime_bridge.json",
    },
    "external_dyn_desc_fault_overwrite_chain_ref": {
        "snn_baseline": "external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json",
        "runtime_bridge": "external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json",
    },
    "barrier_wfi_order_ref": {
        "snn_baseline": "barrier_wfi_order_ref_snn_baseline.json",
        "runtime_bridge": "barrier_wfi_order_ref_runtime_bridge.json",
    },
    "queue_backpressure_ref": {
        "snn_baseline": "queue_backpressure_ref_snn_baseline.json",
        "runtime_bridge": "queue_backpressure_ref_runtime_bridge.json",
    },
    "completion_queue_overflow_ref": {
        "snn_baseline": "completion_queue_overflow_ref_snn_baseline.json",
        "runtime_bridge": "completion_queue_overflow_ref_runtime_bridge.json",
    },
}
EQUIV_MATRIX_GROUPS = {
    "all": tuple(sorted(EQUIV_FAMILY_SPECS)),
}
EQUIV_FAMILY_POLICIES: dict[str, dict[str, Any]] = {}
STRICT_EQUIV_FIELDS = [
    ("schema_version",),
    ("model", "exec_mode"),
    ("model", "mesh_size"),
    ("contracts", "gas_semantic_ready_before_commit"),
    ("contracts", "gas_semantic_drain_before_scatter"),
]
TREND_EQUIV_FIELDS = [
    ("memory", "memory_requests"),
    ("memory", "memory_bytes"),
    ("gas", "windows"),
    ("gas", "windows_done"),
    ("step", "global_steps_done"),
    ("snn_tx", "spike_packets_total"),
    ("snn_rx", "spike_packets_total"),
]
RUNTIME_BRIDGE_RUNTIME_STATS = [
    "riscv_snn_workload_selected",
    "riscv_snn_firmware_elf_present",
    "riscv_snn_firmware_loaded",
    "riscv_snn_backend_runtime_bridge",
    "riscv_snn_firmware_started_count",
    "riscv_snn_submitted_commands",
    "riscv_snn_accepted_commands",
    "riscv_snn_fused_step_completion_count",
    "riscv_snn_completion_visible_count",
    "riscv_snn_completion_consumed_count",
    "riscv_snn_fault_count",
    "riscv_snn_last_completion_status",
    "riscv_snn_last_fault_csr",
    "riscv_snn_backend_runtime_bridge_provider_bound",
]
EQUIV_VALIDATION_FAIL_WAIVERS = {
    ("external_dyn_desc_ref", "snn_baseline"): {
        "name": "external_dyn_desc_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("external_dyn_desc_fault_ref", "snn_baseline"): {
        "name": "external_dyn_desc_fault_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("external_dyn_desc_bad_policy_ref", "snn_baseline"): {
        "name": "external_dyn_desc_bad_policy_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("external_dyn_desc_fault_rearm_ref", "snn_baseline"): {
        "name": "external_dyn_desc_fault_rearm_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("external_dyn_desc_fault_overwrite_chain_ref", "snn_baseline"): {
        "name": "external_dyn_desc_fault_overwrite_chain_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("barrier_wfi_order_ref", "snn_baseline"): {
        "name": "barrier_wfi_order_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("queue_backpressure_ref", "snn_baseline"): {
        "name": "queue_backpressure_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
    ("completion_queue_overflow_ref", "snn_baseline"): {
        "name": "completion_queue_overflow_ref_step_activation_window_alignment",
        "allowed_fail_checks": [
            "step_activation.invocations_vs_windows",
        ],
    },
}
TREND_EQUIV_FIELD_GUIDANCE = {
    "memory.memory_requests": {
        "classification": "traffic_cost_delta",
        "gate_level": "info",
        "policy": {
            "policy_id": "memory_cost_research_surface",
            "enforcement": "informational",
            "expected_relation": "allow_divergence",
            "summary": "Memory request deltas are treated as research-level datapath cost drift.",
        },
        "note": "Memory request totals are a datapath cost surface only; they are informative for research comparison, not a PASS blocker.",
    },
    "memory.memory_bytes": {
        "classification": "traffic_cost_delta",
        "gate_level": "info",
        "policy": {
            "policy_id": "memory_cost_research_surface",
            "enforcement": "informational",
            "expected_relation": "allow_divergence",
            "summary": "Memory byte deltas are treated as research-level datapath cost drift.",
        },
        "note": "Memory byte totals track shadow datapath cost rather than protocol equivalence; they are not a PASS blocker.",
    },
    "gas.windows": {
        "classification": "window_accounting_delta",
        "gate_level": "info",
        "policy": {
            "policy_id": "gas_window_accounting_surface",
            "enforcement": "informational",
            "expected_relation": "allow_divergence",
            "summary": "Window count drift is tracked as research accounting, not as a PASS blocker.",
        },
        "note": "GAS window counts are a high-level accounting surface; drift here is informative, not a PASS blocker.",
    },
    "gas.windows_done": {
        "classification": "window_accounting_delta",
        "gate_level": "info",
        "policy": {
            "policy_id": "gas_window_accounting_surface",
            "enforcement": "informational",
            "expected_relation": "allow_divergence",
            "summary": "Completed window drift is tracked as research accounting, not as a PASS blocker.",
        },
        "note": "Completed GAS windows remain a research compare surface only; drift here is not a PASS blocker.",
    },
    "step.global_steps_done": {
        "classification": "step_progress_delta",
        "gate_level": "info",
        "policy": {
            "policy_id": "step_progress_sanity_surface",
            "enforcement": "informational",
            "expected_relation": "prefer_alignment",
            "summary": "Global step progress is a coarse sanity surface and remains informational.",
        },
        "note": "Global step progress is tracked as a coarse sanity signal and is not currently a PASS blocker.",
    },
    "snn_tx.spike_packets_total": {
        "classification": "traffic_visibility_delta",
        "gate_level": "warn",
        "policy": {
            "policy_id": "transport_visibility_surface",
            "enforcement": "warn_on_visibility_gap",
            "expected_relation": "require_visibility",
            "summary": "Transport visibility should eventually be exported on both sides; missing export is a WARN gate.",
        },
        "note": "Spike TX totals depend on the current export surface; visibility gaps here are informative only, not a PASS blocker.",
    },
    "snn_rx.spike_packets_total": {
        "classification": "traffic_visibility_delta",
        "gate_level": "warn",
        "policy": {
            "policy_id": "transport_visibility_surface",
            "enforcement": "warn_on_visibility_gap",
            "expected_relation": "require_visibility",
            "summary": "Transport visibility should eventually be exported on both sides; missing export is a WARN gate.",
        },
        "note": "Spike RX totals depend on the current export surface; visibility gaps here are informative only, not a PASS blocker.",
    },
}
FAMILY_LANE_RUNTIME_PARAM_FIELDS = (
    "hart_isa",
    "local_mem_bytes",
    "cmd_queue_entries",
    "cmp_queue_entries",
    "rx_debug_queue_entries",
    "boot_addr",
)
FAMILY_LANE_PRESETS: dict[str, dict[str, Any]] = {
    "queue_backpressure_capacity_relief": {
        "family": "queue_backpressure_ref",
        "overrides": {
            "local_mem_bytes": 131072,
        },
        "research_surface_role": "research_lane_capacity_relief",
        "included_in_stable_authority": False,
        "description": (
            "Research-only queue_backpressure subset lane that relaxes local memory pressure without changing "
            "queue-depth semantics."
        ),
    },
}

FAMILY_LANE_MATRIX_PRESETS: dict[str, dict[str, Any]] = {
    "cmpq_fault_rearm_default": {
        "families": (
            "external_dyn_desc_fault_ref",
            "external_dyn_desc_fault_rearm_ref",
            "completion_queue_overflow_ref",
        ),
        "overrides": {
            "cmp_queue_entries": 1,
        },
        "research_surface_role": "default_subset_staircase",
        "included_in_stable_authority": False,
        "description": (
            "Default cmpq-focused subset staircase covering accepted-fault, clear-then-refault, "
            "and completion-overflow queue behavior."
        ),
    },
    "cmpq_fault_overwrite_sibling": {
        "families": (
            "external_dyn_desc_fault_ref",
            "external_dyn_desc_fault_overwrite_chain_ref",
            "completion_queue_overflow_ref",
        ),
        "overrides": {
            "cmp_queue_entries": 1,
        },
        "research_surface_role": "sibling_subset_staircase",
        "included_in_stable_authority": False,
        "description": (
            "Adjacent cmpq-focused subset staircase that swaps rearm semantics for overwrite-chain semantics."
        ),
    },
}


def run_command(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, cwd=cwd, check=False)


def _family_lane_preset_names(*, mode: str | None = None) -> tuple[str, ...]:
    if mode == "matrix":
        return tuple(sorted(FAMILY_LANE_MATRIX_PRESETS))
    if mode in {None, "lane"}:
        return tuple(sorted(FAMILY_LANE_PRESETS))
    raise ValueError(f"unknown family-lane preset mode: {mode}")


def _resolve_family_lane_preset(preset: str | None,
                                *,
                                mode: str | None = None) -> dict[str, Any] | None:
    if preset is None:
        return None
    if mode == "matrix":
        source = FAMILY_LANE_MATRIX_PRESETS
        error_prefix = "family-lane-matrix"
    elif mode in {None, "lane"}:
        source = FAMILY_LANE_PRESETS
        error_prefix = "family-lane"
    else:
        raise ValueError(f"unknown family-lane preset mode: {mode}")
    try:
        payload = source[preset]
    except KeyError as exc:
        raise ValueError(f"unknown {error_prefix} preset: {preset}") from exc
    resolved = dict(payload)
    if "families" in resolved:
        resolved["families"] = list(resolved.get("families") or [])
    normalized_overrides = resolved.get("overrides")
    if normalized_overrides is None:
        normalized_overrides = resolved.get("lane_overrides")
    resolved["overrides"] = dict(normalized_overrides or {})
    return resolved


def _ensure_success(proc: subprocess.CompletedProcess[str], action: str) -> subprocess.CompletedProcess[str]:
    if proc.returncode != 0:
        raise RuntimeError(f"{action} failed\n{proc.stdout}{proc.stderr}".strip())
    return proc


def _resolve_snndl_root(*, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root.parent / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL"


def _resolve_existing_spec(*,
                           program: str | None = None,
                           spec_path: Path | None = None,
                           lab_root: Path = LAB_ROOT,
                           runner: Runner = run_command,
                           action: str) -> Path:
    if program and spec_path is None and _is_toolchain_program(program, lab_root=lab_root):
        _, resolved_spec = _build_toolchain_program(program, lab_root=lab_root, runner=runner)
    else:
        resolved_spec = spec_path or (default_spec_path(program, lab_root=lab_root) if program else None)
    if resolved_spec is None:
        raise ValueError(f"{action} requires --program or --spec")
    return resolved_spec


def _resolve_build_freshness_contract(payload: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    workload_impl = _nested_value(payload, ("workload", "impl"))
    backend_name = _nested_value(payload, ("workload", "params", "backend_name"))
    if not isinstance(workload_impl, str) or not isinstance(backend_name, str):
        return None, None, None
    return workload_impl, backend_name, BUILD_FRESHNESS_CONTRACTS.get((workload_impl, backend_name))


def _build_freshness_rebuild_command(snndl_root: Path, contract: dict[str, Any]) -> str:
    make_terms = ["make"]
    for source_relpath, target_relpath in contract["rebuild_targets"]:
        make_terms.extend(["-W", f"\"{source_relpath}\"", f"\"{target_relpath}\""])
    make_terms.append("\"libSnnDL.la\"")
    return f"cd \"{snndl_root}\"\n" + " ".join(make_terms)


def _runtime_bridge_layout_sensitive_relpaths(contract: dict[str, Any] | None) -> list[str]:
    if contract is None:
        return []
    relpaths = [
        *(str(path) for path in contract.get("dependency_relpaths", ())),
        *(str(path) for path in contract.get("required_target_relpaths", ())),
    ]
    return _sorted_unique(relpaths)


def _resolve_installed_snndl_lib_path(*,
                                      lab_root: Path = LAB_ROOT,
                                      workspace_lib_path: Path | None = None) -> Path | None:
    repo_root = lab_root.parent
    relpath = Path("lib") / "sst-elements-library" / "libSnnDL.so"
    candidates = [
        repo_root / "sst_install" / relpath,
        repo_root / "sst_install_mpi" / relpath,
        repo_root / "sst_install_serial" / relpath,
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None

    workspace_fingerprint = _sha256(workspace_lib_path) if workspace_lib_path and workspace_lib_path.exists() else None
    if workspace_fingerprint is not None:
        matching = [path for path in existing if _sha256(path) == workspace_fingerprint]
        if matching:
            return max(matching, key=lambda path: path.stat().st_mtime_ns)

    return max(existing, key=lambda path: path.stat().st_mtime_ns)


def runtime_bridge_build_guard(*,
                               spec_path: Path,
                               lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    payload = _load_json(spec_path)
    workload_impl, backend_name, contract = _resolve_build_freshness_contract(payload)
    enabled = contract is not None
    snndl_root = _resolve_snndl_root(lab_root=lab_root)
    workspace_lib_path = snndl_root / ".libs" / "libSnnDL.so"
    installed_lib_path = _resolve_installed_snndl_lib_path(
        lab_root=lab_root,
        workspace_lib_path=workspace_lib_path,
    )
    dependency_paths = [str(snndl_root / relpath) for relpath in contract["dependency_relpaths"]] if contract else []
    required_target_paths = [str(snndl_root / relpath) for relpath in contract["required_target_relpaths"]] if contract else []
    summary = {
        "enabled": enabled,
        "status": "skipped",
        "required_action": "none",
        "lineage_status": "skipped",
        "spec_path": str(spec_path),
        "snndl_root": str(snndl_root),
        "workload_impl": workload_impl,
        "backend_name": backend_name,
        "contract_key": contract["contract_key"] if contract else None,
        "contract_version": contract["contract_version"] if contract else None,
        "dependency_paths": dependency_paths,
        "required_target_paths": required_target_paths,
        "stale_targets": [],
        "missing_targets": [],
        "workspace_lib_path": str(workspace_lib_path),
        "installed_lib_path": str(installed_lib_path) if installed_lib_path is not None else None,
        "workspace_build_fingerprint": _sha256(workspace_lib_path) if workspace_lib_path.exists() else None,
        "installed_build_fingerprint": _sha256(installed_lib_path) if installed_lib_path and installed_lib_path.exists() else None,
        "fingerprint_match": None,
        "layout_sensitive_relpaths": _runtime_bridge_layout_sensitive_relpaths(contract),
        "full_rebuild_reason_ids": [],
        "full_rebuild_required": False,
        "rebuild_command": _build_freshness_rebuild_command(snndl_root, contract) if contract else "",
    }
    if not enabled:
        return summary
    if not snndl_root.exists():
        return summary

    dependency_path_objs = [snndl_root / relpath for relpath in contract["dependency_relpaths"]]
    target_path_objs = [snndl_root / relpath for relpath in contract["required_target_relpaths"]]
    missing_targets = [str(path) for path in [*dependency_path_objs, *target_path_objs] if not path.exists()]
    if missing_targets:
        summary["status"] = "missing"
        summary["required_action"] = "incremental_rebuild"
        summary["lineage_status"] = "missing_targets"
        summary["missing_targets"] = missing_targets
        return summary

    newest_dependency_mtime = max(path.stat().st_mtime_ns for path in dependency_path_objs)
    stale_targets = [str(path) for path in target_path_objs if path.stat().st_mtime_ns < newest_dependency_mtime]
    summary["stale_targets"] = stale_targets
    summary["status"] = "stale" if stale_targets else "ok"
    summary["required_action"] = "incremental_rebuild" if stale_targets else "none"
    summary["lineage_status"] = "stale_targets" if stale_targets else "ok"
    workspace_fingerprint = summary.get("workspace_build_fingerprint")
    installed_fingerprint = summary.get("installed_build_fingerprint")
    if workspace_fingerprint is not None and installed_fingerprint is not None:
        summary["fingerprint_match"] = workspace_fingerprint == installed_fingerprint
        if not summary["fingerprint_match"] and summary["status"] == "ok":
            summary["required_action"] = "full_clean_rebuild"
            summary["lineage_status"] = "fingerprint_mismatch"
            summary["full_rebuild_reason_ids"] = ["installed_library_fingerprint_mismatch"]
            summary["full_rebuild_required"] = True
    elif summary["status"] == "ok":
        summary["fingerprint_match"] = None
    return summary


def _format_runtime_bridge_build_guard_failure(summary: dict[str, Any]) -> str:
    lines = [
        (
            f"runtime-bridge build preflight failed for {summary['spec_path']} "
            f"(status={summary['status']})"
        ),
        f"required action: {summary.get('required_action', 'none')}",
        f"lineage status: {summary.get('lineage_status', 'unknown')}",
        (
            "selected contract: "
            f"{summary.get('contract_key') or 'none'}"
            + (
                f"@v{summary['contract_version']}"
                if summary.get("contract_version") is not None
                else ""
            )
        ),
        "checked dependencies:",
        *[f"  - {path}" for path in summary.get("dependency_paths", [])],
    ]
    stale_targets = list(summary.get("stale_targets", []))
    missing_targets = list(summary.get("missing_targets", []))
    if stale_targets:
        lines.append("stale targets:")
        lines.extend(f"  - {path}" for path in stale_targets)
    if missing_targets:
        lines.append("missing targets:")
        lines.extend(f"  - {path}" for path in missing_targets)
    if summary.get("workspace_lib_path") or summary.get("installed_lib_path"):
        lines.append(
            "fingerprints: "
            f"workspace={summary.get('workspace_build_fingerprint') or 'none'} "
            f"installed={summary.get('installed_build_fingerprint') or 'none'} "
            f"match={summary.get('fingerprint_match')}"
        )
    if summary.get("full_rebuild_reason_ids"):
        lines.append("full rebuild reasons:")
        lines.extend(f"  - {reason}" for reason in summary["full_rebuild_reason_ids"])
    lines.append("rebuild command:")
    lines.append(str(summary["rebuild_command"]))
    return "\n".join(lines)


def ensure_runtime_bridge_build_guard(*,
                                      spec_path: Path,
                                      lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    summary = runtime_bridge_build_guard(spec_path=spec_path, lab_root=lab_root)
    if summary["status"] in {"stale", "missing"} or bool(summary.get("full_rebuild_required")):
        raise RuntimeError(_format_runtime_bridge_build_guard_failure(summary))
    return summary


def run_runtime_bridge_preflight(*,
                                 program: str | None = None,
                                 spec_path: Path | None = None,
                                 lab_root: Path = LAB_ROOT,
                                 runner: Runner = run_command) -> dict[str, Any]:
    resolved_spec = _resolve_existing_spec(
        program=program,
        spec_path=spec_path,
        lab_root=lab_root,
        runner=runner,
        action="runtime-bridge-preflight",
    )
    return runtime_bridge_build_guard(spec_path=resolved_spec, lab_root=lab_root)


def _build_preflight_rollup(build_preflight: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(build_preflight or {})
    return {
        "enabled": bool(payload.get("enabled")),
        "reporting_scope": "research_only_nonblocking",
        "status": payload.get("status", "not_run"),
        "required_action": payload.get("required_action", "none"),
        "lineage_status": payload.get("lineage_status", "unknown"),
        "contract_key": payload.get("contract_key"),
        "contract_version": payload.get("contract_version"),
        "dependency_count": len(payload.get("dependency_paths", []) or []),
        "required_target_count": len(payload.get("required_target_paths", []) or []),
        "stale_target_count": len(payload.get("stale_targets", []) or []),
        "missing_target_count": len(payload.get("missing_targets", []) or []),
        "fingerprint_match": payload.get("fingerprint_match"),
        "full_rebuild_required": bool(payload.get("full_rebuild_required")),
    }


def _matrix_build_preflight_rollup(family_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rollups = [
        dict(row.get("runtime_bridge_build_preflight_rollup") or {})
        for row in family_rows
        if row.get("runtime_bridge_build_preflight_rollup") is not None
    ]
    enabled_rollups = [rollup for rollup in rollups if rollup.get("enabled")]
    status_counts: dict[str, int] = {}
    required_action_counts: dict[str, int] = {}
    lineage_status_counts: dict[str, int] = {}
    for rollup in enabled_rollups:
        status = str(rollup.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        required_action = str(rollup.get("required_action", "none"))
        required_action_counts[required_action] = required_action_counts.get(required_action, 0) + 1
        lineage_status = str(rollup.get("lineage_status", "unknown"))
        lineage_status_counts[lineage_status] = lineage_status_counts.get(lineage_status, 0) + 1
    return {
        "enabled": bool(enabled_rollups),
        "reporting_scope": "research_only_nonblocking",
        "family_count": len(enabled_rollups),
        "all_ok": all(rollup.get("status") in {"ok", "skipped"} for rollup in enabled_rollups),
        "status_counts": dict(sorted(status_counts.items())),
        "required_action_counts": dict(sorted(required_action_counts.items())),
        "lineage_status_counts": dict(sorted(lineage_status_counts.items())),
        "contract_keys": _sorted_unique(
            [rollup.get("contract_key") for rollup in enabled_rollups if rollup.get("contract_key")]
        ),
        "contract_versions": sorted(
            {
                int(rollup["contract_version"])
                for rollup in enabled_rollups
                if isinstance(rollup.get("contract_version"), int)
            }
        ),
        "stale_family_count": sum(1 for rollup in enabled_rollups if rollup.get("status") == "stale"),
        "missing_family_count": sum(1 for rollup in enabled_rollups if rollup.get("status") == "missing"),
        "full_rebuild_required_family_count": sum(
            1 for rollup in enabled_rollups if bool(rollup.get("full_rebuild_required"))
        ),
        "fingerprint_mismatch_family_count": sum(
            1 for rollup in enabled_rollups if rollup.get("lineage_status") == "fingerprint_mismatch"
        ),
    }


def default_elf_path(program: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "firmware" / f"{program}.elf"


def default_spec_path(program: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "specs" / f"{program}.json"


def default_manifest_path(program: str,
                          *,
                          lab_root: Path = LAB_ROOT,
                          date_str: str | None = None) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    return lab_root / "runs" / f"{stamp}-{program.replace('_', '-')}-smoke.md"


def default_reference_path(name: str,
                           *,
                           lab_root: Path = LAB_ROOT,
                           date_str: str | None = None) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    return lab_root / "references" / f"{stamp}-{name}.json"


def stable_reference_path(name: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "references" / f"{name}.json"


def stable_markdown_path(name: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "references" / f"{name}.md"


def _compare_stable_surface_paths(*, lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    references_root = lab_root.parent / "sst_dram_si" / "references"
    return {
        "report_path": references_root / "compare-nightly-report.json",
        "observer_summary_path": references_root / "compare-nightly-observer-summary.json",
        "summary_md_path": references_root / "compare-nightly-summary.md",
        "current_mainline_status_path": references_root / "compare-current-status.md",
    }


def _reference_compare_stable_surface_paths(*, lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    references_root = LAB_ROOT / "references"
    return {
        "history_path": references_root / "reference-compare-history.json",
        "report_path": references_root / "reference-compare-nightly-report.json",
        "summary_md_path": references_root / "reference-compare-nightly-summary.md",
        "current_mainline_status_path": references_root / "reference-compare-current-status.md",
    }


def _reference_program_compare_stable_surface_paths(*, lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    references_root = lab_root / "references"
    return {
        "history_path": references_root / "reference-program-compare-history.json",
        "report_path": references_root / "reference-program-compare-nightly-report.json",
        "summary_md_path": references_root / "reference-program-compare-nightly-summary.md",
        "current_mainline_status_path": references_root / "reference-program-compare-current-status.md",
    }


def _stat_snapshot_family_stable_surface_paths(*, lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    references_root = lab_root / "references"
    return {
        "history_path": references_root / "stat-snapshot-family-history.json",
        "report_path": references_root / "stat-snapshot-family-nightly-report.json",
        "summary_md_path": references_root / "stat-snapshot-family-nightly-summary.md",
        "current_mainline_status_path": references_root / "stat-snapshot-family-current-status.md",
        "observer_summary_path": references_root / "nightly-sidecar-observer-summary.json",
    }


def _camel_to_snake(name: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


def _stat_snapshot_selector_program_candidates(selector_name: str) -> list[str]:
    slug = _camel_to_snake(selector_name)
    aliases = [slug]
    if slug.endswith("_commands"):
        aliases.append(slug[: -len("_commands")])
    if slug == "accepted_commands":
        aliases.append("")
    candidates: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        base_program = "stat_snapshot_ref" if not alias else f"stat_snapshot_{alias}_ref"
        if base_program in seen:
            continue
        seen.add(base_program)
        candidates.append(base_program)
    return candidates


def _firmware_path_from_spec(spec_path: Path, *, fallback: Path) -> Path:
    if spec_path.exists():
        try:
            payload = _load_json(spec_path)
            firmware_path = (
                dict(dict(payload.get("workload") or {}).get("params") or {}).get("firmware_elf")
            )
            if str(firmware_path or "").strip():
                return Path(str(firmware_path))
        except Exception:
            pass
    return fallback


def _stat_snapshot_validate_spec(
    spec_path: Path,
    *,
    lab_root: Path = LAB_ROOT,
    runner: Runner = run_command,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cache_key = str(spec_path.resolve()) if spec_path.exists() else str(spec_path)
    cached = cache.get(cache_key)
    if cached is not None:
        return dict(cached)
    result = {
        "present": spec_path.exists(),
        "validate_ok": None,
        "validate_error": None,
    }
    if result["present"]:
        try:
            validate_program(
                spec_path=spec_path,
                lab_root=lab_root,
                runner=runner,
            )
            result["validate_ok"] = True
        except Exception as exc:
            result["validate_ok"] = False
            result["validate_error"] = str(exc)
    cache[cache_key] = dict(result)
    return dict(result)


def _stat_snapshot_selector_reference_row(
    selector_name: str,
    selector_value: int,
    *,
    lab_root: Path = LAB_ROOT,
    runner: Runner = run_command,
    validate_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates = _stat_snapshot_selector_program_candidates(selector_name)
    chosen_payload: dict[str, Any] | None = None
    chosen_score = -1
    for base_program in candidates:
        runtime_program = base_program
        toolchain_program = f"{base_program}_toolchain"
        runtime_spec_path = default_spec_path(runtime_program, lab_root=lab_root)
        runtime_bridge_spec_path = default_spec_path(f"{base_program}_runtime_bridge", lab_root=lab_root)
        toolchain_spec_path = default_spec_path(toolchain_program, lab_root=lab_root)
        runtime_elf_path = _firmware_path_from_spec(
            runtime_spec_path,
            fallback=default_elf_path(runtime_program, lab_root=lab_root),
        )
        toolchain_elf_path = _firmware_path_from_spec(
            toolchain_spec_path,
            fallback=default_elf_path(toolchain_program, lab_root=lab_root),
        )
        toolchain_source_path = toolchain_source_dir(toolchain_program, lab_root=lab_root)
        present_paths = (
            runtime_spec_path,
            runtime_bridge_spec_path,
            runtime_elf_path,
            toolchain_source_path,
            toolchain_spec_path,
            toolchain_elf_path,
        )
        score = sum(1 for path in present_paths if path.exists())
        payload = {
            "selector_name": selector_name,
            "selector_value": selector_value,
            "selector_slug": _camel_to_snake(selector_name),
            "program": runtime_program,
            "toolchain_program": toolchain_program,
            "candidate_programs": list(candidates),
            "runtime_spec_path": str(runtime_spec_path),
            "runtime_spec_present": runtime_spec_path.exists(),
            "runtime_bridge_spec_path": str(runtime_bridge_spec_path),
            "runtime_bridge_spec_present": runtime_bridge_spec_path.exists(),
            "runtime_elf_path": str(runtime_elf_path),
            "runtime_elf_present": runtime_elf_path.exists(),
            "toolchain_source_path": str(toolchain_source_path),
            "toolchain_source_present": toolchain_source_path.exists(),
            "toolchain_spec_path": str(toolchain_spec_path),
            "toolchain_spec_present": toolchain_spec_path.exists(),
            "toolchain_elf_path": str(toolchain_elf_path),
            "toolchain_elf_present": toolchain_elf_path.exists(),
            "score": score,
        }
        if score > chosen_score:
            chosen_payload = payload
            chosen_score = score

    if chosen_payload is None:
        raise RuntimeError(f"stat snapshot selector discovery failed: {selector_name}")

    runtime_spec_path = Path(chosen_payload["runtime_spec_path"])
    runtime_bridge_spec_path = Path(chosen_payload["runtime_bridge_spec_path"])
    toolchain_spec_path = Path(chosen_payload["toolchain_spec_path"])
    runtime_validation = _stat_snapshot_validate_spec(
        runtime_spec_path,
        lab_root=lab_root,
        runner=runner,
        cache=validate_cache,
    )
    runtime_bridge_validation = _stat_snapshot_validate_spec(
        runtime_bridge_spec_path,
        lab_root=lab_root,
        runner=runner,
        cache=validate_cache,
    )
    toolchain_validation = _stat_snapshot_validate_spec(
        toolchain_spec_path,
        lab_root=lab_root,
        runner=runner,
        cache=validate_cache,
    )
    missing_assets: list[str] = []
    validation_failures: list[str] = []
    required_presence_fields = (
        ("runtime_spec_present", "runtime_spec"),
        ("runtime_bridge_spec_present", "runtime_bridge_spec"),
        ("runtime_elf_present", "runtime_elf"),
        ("toolchain_source_present", "toolchain_source"),
        ("toolchain_spec_present", "toolchain_spec"),
        ("toolchain_elf_present", "toolchain_elf"),
    )
    for field_name, label in required_presence_fields:
        if not chosen_payload.get(field_name):
            missing_assets.append(label)
    for label, validation in (
        ("runtime_spec", runtime_validation),
        ("runtime_bridge_spec", runtime_bridge_validation),
        ("toolchain_spec", toolchain_validation),
    ):
        if validation.get("validate_ok") is False:
            validation_failures.append(label)
    latest_source_date = None
    source_dates = [
        dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).date().isoformat()
        for path in (
            Path(chosen_payload["runtime_spec_path"]),
            Path(chosen_payload["runtime_bridge_spec_path"]),
            Path(chosen_payload["runtime_elf_path"]),
            Path(chosen_payload["toolchain_source_path"]),
            Path(chosen_payload["toolchain_spec_path"]),
            Path(chosen_payload["toolchain_elf_path"]),
        )
        if path.exists()
    ]
    if source_dates:
        latest_source_date = max(source_dates)
    chosen_payload.update(
        {
            "runtime_spec_validate_ok": runtime_validation.get("validate_ok"),
            "runtime_spec_validate_error": runtime_validation.get("validate_error"),
            "runtime_bridge_spec_validate_ok": runtime_bridge_validation.get("validate_ok"),
            "runtime_bridge_spec_validate_error": runtime_bridge_validation.get("validate_error"),
            "toolchain_spec_validate_ok": toolchain_validation.get("validate_ok"),
            "toolchain_spec_validate_error": toolchain_validation.get("validate_error"),
            "missing_assets": missing_assets,
            "validation_failures": validation_failures,
            "reference_ready": not missing_assets and not validation_failures,
            "latest_source_date": latest_source_date,
        }
    )
    return chosen_payload


def _stat_snapshot_family_selector_rows(
    *,
    lab_root: Path = LAB_ROOT,
    runner: Runner = run_command,
) -> list[dict[str, Any]]:
    authority = load_accel_authority(lab_root=lab_root)
    selector_values = (
        dict(
            dict(dict(authority.get("stat_snapshot_surface") or {}).get("selector_surface") or {}).get("values")
            or {}
        )
    )
    validate_cache: dict[str, dict[str, Any]] = {}
    rows = [
        _stat_snapshot_selector_reference_row(
            selector_name,
            int(selector_value),
            lab_root=lab_root,
            runner=runner,
            validate_cache=validate_cache,
        )
        for selector_name, selector_value in sorted(
            selector_values.items(),
            key=lambda item: int(item[1]),
        )
    ]
    return rows


def default_reference_compare_family_summary_path(
    family: str,
    *,
    lab_root: Path = LAB_ROOT,
    date_str: str | None = None,
) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    return lab_root / "references" / f"{stamp}-{family.replace('_', '-')}-reference-compare.json"


def default_reference_compare_matrix_summary_path(
    *,
    group: str = "all",
    lab_root: Path = LAB_ROOT,
    date_str: str | None = None,
) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    suffix = "" if group == "all" else f"-{group.replace('_', '-')}"
    return lab_root / "references" / f"{stamp}-reference-compare-matrix{suffix}.json"


def default_reference_program_compare_family_summary_path(
    family: str,
    *,
    lab_root: Path = LAB_ROOT,
    date_str: str | None = None,
) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    return lab_root / "references" / f"{stamp}-{family.replace('_', '-')}-reference-program-compare.json"


def default_reference_program_compare_matrix_summary_path(
    *,
    group: str = "all",
    lab_root: Path = LAB_ROOT,
    date_str: str | None = None,
) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    suffix = "" if group == "all" else f"-{group.replace('_', '-')}"
    return lab_root / "references" / f"{stamp}-reference-program-compare-matrix{suffix}.json"


def _normalize_supplementary_surface(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    raw = dict(payload or {})
    gate_reasons = raw.get("gate_reasons")
    if not isinstance(gate_reasons, list):
        gate_reasons = []
    authority_surface = _supplementary_surface_authority_surface(name, lab_root=lab_root)
    authority_surface_kind = str(authority_surface.get("surface_kind") or "").strip()
    surface_kind = str(raw.get("surface_kind") or "").strip()
    if not surface_kind:
        surface_kind = authority_surface_kind or (
            "compare_exec_mode_smoke" if name == "compare" else f"{name}_supplementary_surface"
        )
    blocking_default = authority_surface.get("blocking")
    if blocking_default is None:
        blocking_default = False
    return {
        "surface_kind": surface_kind,
        "blocking": bool(raw.get("blocking", blocking_default)),
        "present": bool(raw.get("present", False)),
        "load_error": raw.get("load_error"),
        "report_path": raw.get("report_path"),
        "observer_summary_path": raw.get("observer_summary_path"),
        "summary_md_path": raw.get("summary_md_path"),
        "current_mainline_status_path": raw.get("current_mainline_status_path"),
        "artifact_role": raw.get("artifact_role"),
        "authority_scope": raw.get("authority_scope"),
        "gate_name": raw.get("gate_name"),
        "gate_version": raw.get("gate_version"),
        "gate_ok": raw.get("gate_ok"),
        "gate_reasons": [str(reason) for reason in gate_reasons if str(reason).strip()],
        "latest_date": raw.get("latest_date"),
        "stale": raw.get("stale"),
        "freshness_mode": raw.get("freshness_mode"),
        "effective_all_dates_ok": raw.get("effective_all_dates_ok"),
        "surface_contract": raw.get("surface_contract"),
        "selector_rows": [
            dict(row)
            for row in list(raw.get("selector_rows") or [])
            if isinstance(row, dict)
        ],
        "selector_count": raw.get("selector_count"),
        "covered_selector_count": raw.get("covered_selector_count"),
    }


def _supplementary_surface_rollup(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    surface = _normalize_supplementary_surface(name, payload, lab_root=lab_root)
    load_error = surface.get("load_error")
    freshness_ok = (
        surface.get("stale") is False
        and surface.get("effective_all_dates_ok") is True
    )
    healthy = (
        surface.get("present") is True
        and not load_error
        and surface.get("gate_ok") is True
        and freshness_ok
    )
    if surface.get("present") is not True:
        status = "absent"
    elif healthy:
        status = "pass"
    else:
        status = "degraded"
    return {
        "surface_kind": surface.get("surface_kind"),
        "present": surface.get("present"),
        "blocking": surface.get("blocking"),
        "status": status,
        "healthy": healthy,
        "freshness_ok": freshness_ok,
        "load_error": load_error,
        "gate_ok": surface.get("gate_ok"),
        "latest_date": surface.get("latest_date"),
        "stale": surface.get("stale"),
        "freshness_mode": surface.get("freshness_mode"),
        "effective_all_dates_ok": surface.get("effective_all_dates_ok"),
        "selector_count": surface.get("selector_count"),
        "covered_selector_count": surface.get("covered_selector_count"),
        "report_path": surface.get("report_path"),
        "current_mainline_status_path": surface.get("current_mainline_status_path"),
        "summary_md_path": surface.get("summary_md_path"),
    }


def _report_supplementary_surfaces(
    report: dict[str, Any],
    *,
    lab_root: Path = LAB_ROOT,
) -> dict[str, dict[str, Any]]:
    return {
        name: _normalize_supplementary_surface(name, payload, lab_root=lab_root)
        for name, payload in dict(report.get("supplementary_surfaces", {}) or {}).items()
        if isinstance(payload, dict)
    }


def _supplementary_history_surface(
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    surface = _normalize_supplementary_surface(name, payload, lab_root=lab_root)
    source_report_path = Path(str(surface.get("report_path"))) if surface.get("report_path") else None
    source_report: dict[str, Any] = {}
    source_history: dict[str, Any] = {}
    history_path = None
    if source_report_path is not None and source_report_path.exists():
        try:
            source_report = _load_json(source_report_path)
        except Exception:
            source_report = {}
    history_meta = dict(source_report.get("history") or {})
    if history_meta.get("path"):
        history_path = Path(str(history_meta.get("path")))
        if history_path.exists():
            try:
                source_history = _load_json(history_path)
            except Exception:
                source_history = {}
    history_payload = dict(history_meta)
    history_payload.update({k: v for k, v in source_history.items() if k not in history_payload or history_payload.get(k) is None})
    history_contract = history_payload.get("history_contract")
    if not history_contract:
        history_contract = str(
            _supplementary_surface_authority_surface(name, lab_root=lab_root).get("source_history_contract")
            or f"{name}_source_history_passthrough_v1"
        )
    entries = list(history_payload.get("entries", []) or [])
    return {
        "surface_kind": surface.get("surface_kind"),
        "blocking": surface.get("blocking"),
        "present": surface.get("present"),
        "load_error": surface.get("load_error"),
        "report_path": surface.get("report_path"),
        "observer_summary_path": surface.get("observer_summary_path"),
        "summary_md_path": surface.get("summary_md_path"),
        "current_mainline_status_path": surface.get("current_mainline_status_path"),
        "gate_ok": surface.get("gate_ok"),
        "history_path": str(history_path) if history_path is not None else history_payload.get("path"),
        "history_contract": history_contract,
        "latest_date": history_payload.get("latest_date", surface.get("latest_date")),
        "entry_count": int(history_payload.get("entry_count", 0) or 0),
        "excluded_entry_count": int(history_payload.get("excluded_entry_count", 0) or 0),
        "all_ok_latest": history_payload.get("all_ok_latest", surface.get("gate_ok")),
        "all_dates_ok": history_payload.get("all_dates_ok"),
        "latest_recovered_date": history_payload.get("latest_recovered_date"),
        "stale": history_payload.get("stale", surface.get("stale")),
        "freshness_mode": history_payload.get("freshness_mode", surface.get("freshness_mode")),
        "effective_entry_count": history_payload.get("effective_entry_count"),
        "effective_all_dates_ok": history_payload.get(
            "effective_all_dates_ok",
            surface.get("effective_all_dates_ok"),
        ),
        "selector_count": surface.get("selector_count"),
        "covered_selector_count": surface.get("covered_selector_count"),
        "entries": entries,
    }


def refresh_supplementary_surface_history(*,
                                          sidecar_report: dict[str, Any] | None = None,
                                          sidecar_path: Path | None = None,
                                          output_path: Path | None = None,
                                          lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    report = sidecar_report
    if report is None:
        report = _load_json(resolved_sidecar_path)
    surfaces = _report_supplementary_surfaces(report, lab_root=lab_root)
    authority = load_supplementary_surface_authority(lab_root=lab_root)
    resolved_output_path = output_path or stable_reference_path("supplementary-surface-history", lab_root=lab_root)
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_SUPPLEMENTARY_SURFACE_HISTORY,
            scope="observer_surface_only",
            producer="riscv_snn_lab.refresh_supplementary_surface_history",
        ),
        "history_contract": str(authority.get("history_contract") or "supplementary_surface_observer_v1"),
        "contract_name": authority.get("contract_name"),
        "contract_version": authority.get("contract_version"),
        "authority_path": str(
            _resolve_authority_path(
                lab_root=lab_root,
                default_path=SUPPLEMENTARY_SURFACE_AUTHORITY_PATH,
            )
        ),
        "sidecar_path": str(resolved_sidecar_path),
        "surface_count": len(surfaces),
        "surfaces": {
            name: _supplementary_history_surface(name, payload, lab_root=lab_root)
            for name, payload in surfaces.items()
        },
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, history)
    return history


def _load_compare_supplementary_surface(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    surface_paths = _compare_stable_surface_paths(lab_root=lab_root)
    payload = _normalize_supplementary_surface("compare", {
        "surface_kind": "compare_exec_mode_smoke",
        "blocking": False,
        "present": False,
        "load_error": None,
        "report_path": str(surface_paths["report_path"]),
        "observer_summary_path": str(surface_paths["observer_summary_path"]),
        "summary_md_path": str(surface_paths["summary_md_path"]),
        "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        "artifact_role": None,
        "authority_scope": None,
        "gate_name": None,
        "gate_version": None,
        "gate_ok": None,
        "gate_reasons": [],
        "latest_date": None,
        "stale": None,
        "freshness_mode": None,
        "effective_all_dates_ok": None,
    }, lab_root=lab_root)
    if not surface_paths["report_path"].exists():
        return payload

    payload["present"] = True
    try:
        report = _load_json(surface_paths["report_path"])
    except Exception as exc:
        payload["load_error"] = str(exc)
        return payload

    payload = supplementary_surface_contract.project_surface_payload_from_report(
        default_payload=payload,
        report=report,
        stable_surface_fields=(
            "report_path",
            "observer_summary_path",
            "summary_md_path",
            "current_mainline_status_path",
        ),
        history_fields=("latest_date", "stale", "freshness_mode", "effective_all_dates_ok"),
        report_fields=("artifact_role", "authority_scope", "gate_name", "gate_version", "gate_ok"),
        list_report_fields=("gate_reasons",),
    )
    return _normalize_supplementary_surface("compare", payload, lab_root=lab_root)


def _load_reference_compare_supplementary_surface(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    surface_paths = _reference_compare_stable_surface_paths(lab_root=lab_root)
    payload = _normalize_supplementary_surface(
        "reference_compare",
        {
            "surface_kind": "reference_compare_surface",
            "blocking": False,
            "present": False,
            "load_error": None,
            "report_path": str(surface_paths["report_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
            "artifact_role": None,
            "authority_scope": None,
            "gate_name": None,
            "gate_version": None,
            "gate_ok": None,
            "gate_reasons": [],
            "latest_date": None,
            "stale": None,
            "freshness_mode": None,
            "effective_all_dates_ok": None,
        },
        lab_root=lab_root,
    )
    if not surface_paths["report_path"].exists():
        return payload

    payload["present"] = True
    try:
        report = _load_json(surface_paths["report_path"])
    except Exception as exc:
        payload["load_error"] = str(exc)
        return payload

    payload = supplementary_surface_contract.project_surface_payload_from_report(
        default_payload=payload,
        report=report,
        stable_surface_fields=("report_path", "summary_md_path", "current_mainline_status_path"),
        history_fields=("latest_date", "stale", "freshness_mode", "effective_all_dates_ok"),
        report_fields=("artifact_role", "authority_scope", "gate_name", "gate_version", "gate_ok"),
        list_report_fields=("gate_reasons",),
    )
    return _normalize_supplementary_surface("reference_compare", payload, lab_root=lab_root)


def _load_reference_program_compare_supplementary_surface(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    surface_paths = _reference_program_compare_stable_surface_paths(lab_root=lab_root)
    payload = _normalize_supplementary_surface(
        "reference_program_compare",
        {
            "surface_kind": "reference_program_compare_surface",
            "blocking": False,
            "present": False,
            "load_error": None,
            "report_path": str(surface_paths["report_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
            "artifact_role": None,
            "authority_scope": None,
            "gate_name": None,
            "gate_version": None,
            "gate_ok": None,
            "gate_reasons": [],
            "latest_date": None,
            "stale": None,
            "freshness_mode": None,
            "effective_all_dates_ok": None,
        },
        lab_root=lab_root,
    )
    if not surface_paths["report_path"].exists():
        return payload

    payload["present"] = True
    try:
        report = _load_json(surface_paths["report_path"])
    except Exception as exc:
        payload["load_error"] = str(exc)
        return payload

    payload = supplementary_surface_contract.project_surface_payload_from_report(
        default_payload=payload,
        report=report,
        stable_surface_fields=("report_path", "summary_md_path", "current_mainline_status_path"),
        history_fields=("latest_date", "stale", "freshness_mode", "effective_all_dates_ok"),
        report_fields=("artifact_role", "authority_scope", "gate_name", "gate_version", "gate_ok"),
        list_report_fields=("gate_reasons",),
    )
    return _normalize_supplementary_surface("reference_program_compare", payload, lab_root=lab_root)


def _load_stat_snapshot_family_supplementary_surface(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    surface_paths = _stat_snapshot_family_stable_surface_paths(lab_root=lab_root)
    payload = _normalize_supplementary_surface(
        "stat_snapshot_family",
        {
            "surface_kind": "stat_snapshot_family_surface",
            "blocking": False,
            "present": False,
            "load_error": None,
            "report_path": str(surface_paths["report_path"]),
            "observer_summary_path": str(surface_paths["observer_summary_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
            "artifact_role": None,
            "authority_scope": None,
            "gate_name": None,
            "gate_version": None,
            "gate_ok": False,
            "gate_reasons": [],
            "latest_date": "",
            "stale": True,
            "freshness_mode": "latest_refresh_only",
            "effective_all_dates_ok": False,
            "surface_contract": "stat_snapshot_family_surface_v1",
            "selector_rows": [],
            "selector_count": 0,
            "covered_selector_count": 0,
        },
        lab_root=lab_root,
    )
    if not surface_paths["report_path"].exists():
        return payload

    payload["present"] = True
    try:
        report = _load_json(surface_paths["report_path"])
    except Exception as exc:
        payload["load_error"] = str(exc)
        return payload

    payload = supplementary_surface_contract.project_surface_payload_from_report(
        default_payload=payload,
        report=report,
        stable_surface_fields=(
            "report_path",
            "observer_summary_path",
            "summary_md_path",
            "current_mainline_status_path",
        ),
        history_fields=("latest_date", "stale", "freshness_mode", "effective_all_dates_ok"),
        report_fields=(
            "artifact_role",
            "authority_scope",
            "gate_name",
            "gate_version",
            "gate_ok",
            "surface_contract",
            "selector_count",
            "covered_selector_count",
        ),
        list_report_fields=("gate_reasons", "selector_rows"),
    )
    payload["selector_count"] = int(payload.get("selector_count", 0) or 0)
    payload["covered_selector_count"] = int(payload.get("covered_selector_count", 0) or 0)
    return _normalize_supplementary_surface("stat_snapshot_family", payload, lab_root=lab_root)


def _supplementary_surfaces(*, lab_root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    return {
        "compare": _load_compare_supplementary_surface(lab_root=lab_root),
        "reference_compare": _load_reference_compare_supplementary_surface(lab_root=lab_root),
        "reference_program_compare": _load_reference_program_compare_supplementary_surface(
            lab_root=lab_root
        ),
        "stat_snapshot_family": _load_stat_snapshot_family_supplementary_surface(
            lab_root=lab_root
        ),
    }


def _reference_compare_family_equiv_pattern(family: str) -> str:
    return f"*-{family.replace('_', '-')}-equiv.json"


def _latest_reference_compare_family_input(
    family: str,
    *,
    lab_root: Path = LAB_ROOT,
) -> tuple[dict[str, Any], Path]:
    summary_path = _latest_dated_reference(_reference_compare_family_equiv_pattern(family), lab_root=lab_root)
    if summary_path is None or not summary_path.exists():
        raise FileNotFoundError(f"reference compare family input missing: {family}")
    payload = _load_json(summary_path)
    payload.setdefault("summary_path", str(summary_path))
    return payload, summary_path


def _reference_program_primary_input_for_family(
    family: str,
    *,
    lab_root: Path = LAB_ROOT,
) -> tuple[dict[str, Any], Path]:
    if family in EQUIV_FAMILY_SPECS:
        payload, path = _latest_reference_compare_family_input(family, lab_root=lab_root)
        return (
            {
                "source_kind": "equiv_summary",
                "status": payload.get("status"),
                "program": family,
            },
            path,
        )

    manifest_path = _latest_manifest_path(family, lab_root=lab_root)
    if manifest_path is None or not manifest_path.exists():
        return (
            {
                "source_kind": "runtime_manifest",
                "status": "manifest_missing",
                "program": family,
                "manifest_run_dir": None,
            },
            default_manifest_path(family, lab_root=lab_root),
        )
    manifest_text = manifest_path.read_text(encoding="utf-8")
    return (
        {
            "source_kind": "runtime_manifest",
            "status": "manifest_present",
            "program": family,
            "manifest_run_dir": _parse_manifest_run_dir(manifest_text),
        },
        manifest_path,
    )


def _reference_compare_divergence_points_for_family(
    family_policy: dict[str, Any],
    *,
    architecture_authority: dict[str, Any],
) -> list[str]:
    allowed_points = list(((architecture_authority.get("fabric_taxonomy") or {}).get("allowed_divergence_points")) or [])
    if not allowed_points:
        return []
    if str(family_policy.get("timing_mode") or "").strip():
        return [point for point in ["backpressure"] if point in allowed_points]
    if str(family_policy.get("fault_lifecycle_mode") or "").strip() in {"clear_then_refault", "overwrite_chain"}:
        return [point for point in ["queue_occupancy"] if point in allowed_points]
    return []


def _reference_compare_runtime_summary_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
) -> dict[str, Any]:
    terminal_state = "Faulted" if str(family_policy.get("fault_mode") or "") == "accepted_fault_required" else "Completed"
    fabric_stages = ["ingress_receive", "execution_consume"]
    known_stages = {
        str(stage.get("name"))
        for stage in list(((architecture_authority.get("fabric_taxonomy") or {}).get("stages")) or [])
        if isinstance(stage, dict)
    }
    fabric_stages = [stage for stage in fabric_stages if stage in known_stages]
    return {
        "family": family,
        "terminal_state": terminal_state,
        "memory_domains": ["ControlMemory"],
        "fabric_stages": fabric_stages,
        "divergence_points": _reference_compare_divergence_points_for_family(
            family_policy,
            architecture_authority=architecture_authority,
        ),
    }


def _reference_compare_reference_result_for_runtime_summary(
    runtime_summary: dict[str, Any],
    *,
    machine: ReferenceMachine,
) -> Any:
    terminal_state = str(runtime_summary.get("terminal_state") or "Completed")
    if terminal_state == "Faulted":
        condition_values = {
            "fault_classified": True,
            "fault_csr_committed": True,
            "completion_suppressed_or_replaced_by_fault": True,
        }
    else:
        condition_values = {
            "architectural_state_committed": True,
            "local_outbound_handover_complete": True,
            "barrier_release_visible": True,
            "no_higher_priority_fault_pending": True,
        }
    return machine.execute_fused_step(
        condition_values=condition_values,
        metadata={
            "memory_domains": list(runtime_summary.get("memory_domains", []) or []),
            "fabric_stages": list(runtime_summary.get("fabric_stages", []) or []),
            "divergence_points": list(runtime_summary.get("divergence_points", []) or []),
        },
    )


def run_reference_compare_family(
    *,
    family: str,
    summary_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    architecture_authority = load_architecture_model_authority(lab_root=lab_root)
    equiv_summary, equiv_summary_path = _latest_reference_compare_family_input(family, lab_root=lab_root)
    runtime_summary = _reference_compare_runtime_summary_for_family(
        family,
        family_policy=family_policy,
        architecture_authority=architecture_authority,
    )
    machine = ReferenceMachine.from_authority(architecture_authority)
    reference_result = _reference_compare_reference_result_for_runtime_summary(
        runtime_summary,
        machine=machine,
    )
    comparison = compare_reference_to_runtime(
        reference_result,
        runtime_summary,
        allowed_divergence_points=tuple(
            str(point)
            for point in list(
                ((architecture_authority.get("fabric_taxonomy") or {}).get("allowed_divergence_points")) or []
            )
            if str(point).strip()
        ),
    )
    resolved_summary_path = summary_path or default_reference_compare_family_summary_path(
        family,
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role="dated_reference_compare_family_surface",
            scope="reference_compare_only",
            producer="riscv_snn_lab.run_reference_compare_family",
        ),
        "family": family,
        "status": comparison["status"],
        "gate_ok": comparison["gate_ok"],
        "gate_reasons": list(comparison.get("gate_reasons") or []),
        "equiv_summary_path": str(equiv_summary_path),
        "runtime_policy": family_policy,
        "runtime_summary": runtime_summary,
        "reference_terminal_state": reference_result.terminal_state,
        "comparison": comparison,
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    summary["source_equiv_summary_path"] = str(equiv_summary_path)
    summary["source_equiv_status"] = equiv_summary.get("status")
    return summary


def run_reference_compare_matrix(
    *,
    families: list[str] | None = None,
    group: str = "all",
    summary_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    resolved_families = _resolve_equiv_families(families, group=group, lab_root=lab_root)
    family_rows: list[dict[str, Any]] = []
    for family in resolved_families:
        family_summary = run_reference_compare_family(family=family, lab_root=lab_root)
        family_rows.append(
            {
                "family": family_summary["family"],
                "status": family_summary["status"],
                "gate_ok": family_summary["gate_ok"],
                "gate_reasons": list(family_summary.get("gate_reasons") or []),
                "summary_path": family_summary["summary_path"],
            }
        )
    resolved_summary_path = summary_path or default_reference_compare_matrix_summary_path(
        group=group,
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role="dated_reference_compare_matrix",
            scope="reference_compare_only",
            producer="riscv_snn_lab.run_reference_compare_matrix",
        ),
        "group": group,
        "count": len(family_rows),
        "all_ok": all(bool(row.get("gate_ok")) for row in family_rows),
        "gate_reasons": _sorted_unique(
            [
                reason
                for row in family_rows
                for reason in list(row.get("gate_reasons") or [])
            ]
        ),
        "families": family_rows,
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def refresh_reference_compare_surface(
    *,
    families: list[str] | None = None,
    group: str = "all",
    sidecar_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
    refresh_derived_surfaces: bool = True,
) -> dict[str, Any]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    matrix_summary = run_reference_compare_matrix(
        families=families,
        group=group,
        lab_root=lab_root,
    )
    surface_paths = _reference_compare_stable_surface_paths(lab_root=lab_root)
    authority_surface = _supplementary_surface_authority_surface("reference_compare", lab_root=lab_root)
    status = "pass" if matrix_summary.get("all_ok") else "degraded"
    latest_date = dt.date.today().isoformat()
    history_payload = supplementary_surface_contract.build_latest_only_history_payload(
        history_contract=str(
            authority_surface.get("source_history_contract") or "reference_compare_source_history_passthrough_v1"
        ),
        history_path=str(surface_paths["history_path"]),
        latest_date=latest_date,
        gate_ok=bool(matrix_summary.get("all_ok")),
        freshness_mode="reference_compare_latest_only",
        entry_payload={
            "date": latest_date,
            "group": group,
            "count": matrix_summary.get("count"),
            "all_ok": matrix_summary.get("all_ok"),
            "gate_reasons": list(matrix_summary.get("gate_reasons") or []),
        },
    )
    _write_json(surface_paths["history_path"], history_payload)
    report_payload = {
        **_artifact_metadata(
            role="reference_compare_surface_report",
            scope="reference_compare_only",
            producer="riscv_snn_lab.refresh_reference_compare_surface",
        ),
        "gate_name": "reference_model_runtime_compare",
        "gate_version": "1.0",
        "gate_ok": bool(matrix_summary.get("all_ok")),
        "gate_reasons": list(matrix_summary.get("gate_reasons") or []),
        "status": status,
        "matrix_summary_path": matrix_summary.get("summary_path"),
        "group": group,
        "count": matrix_summary.get("count"),
        "families": list(matrix_summary.get("families") or []),
        "stable_surfaces": {
            "report_path": str(surface_paths["report_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        },
        "history": history_payload,
    }
    _write_json(surface_paths["report_path"], report_payload)
    summary_md = supplementary_surface_contract.render_surface_summary_markdown(
        title="reference_compare nightly summary",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", report_payload["gate_ok"]),
            ("group", group),
            ("count", matrix_summary.get("count")),
            ("matrix_summary_path", matrix_summary.get("summary_path")),
            ("latest_date", history_payload["latest_date"]),
            ("freshness_mode", history_payload["freshness_mode"]),
            ("effective_all_dates_ok", history_payload["effective_all_dates_ok"]),
            ("report_path", surface_paths["report_path"]),
            ("current_mainline_status_path", surface_paths["current_mainline_status_path"]),
        ],
    )
    _atomic_write_text(surface_paths["summary_md_path"], summary_md)
    current_status_md = supplementary_surface_contract.render_surface_current_status_markdown(
        title="reference_compare current status",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", report_payload["gate_ok"]),
            ("group", group),
            ("count", matrix_summary.get("count")),
            ("matrix_summary_path", matrix_summary.get("summary_path")),
        ],
    )
    _atomic_write_text(surface_paths["current_mainline_status_path"], current_status_md)

    surface_payload = _normalize_supplementary_surface(
        "reference_compare",
        supplementary_surface_contract.build_surface_attachment(
            authority_surface=authority_surface,
            stable_surfaces=report_payload["stable_surfaces"],
            report_payload=report_payload,
            history_payload=history_payload,
        ),
        lab_root=lab_root,
    )
    sidecar_report = supplementary_surface_contract.merge_supplementary_surface(
        sidecar_report=sidecar_report,
        name="reference_compare",
        surface_payload=surface_payload,
    )
    _write_json(resolved_sidecar_path, sidecar_report)

    if refresh_derived_surfaces:
        _refresh_derived_stable_surfaces(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
        )
    return {
        **surface_payload,
        "status": status,
        "count": matrix_summary.get("count"),
        "summary_path": matrix_summary.get("summary_path"),
    }


def export_reference_compare_surface(*,
                                     reference_result: Any,
                                     runtime_summary: dict[str, Any],
                                     sidecar_path: Path,
                                     lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    architecture_authority = load_architecture_model_authority(lab_root=lab_root)
    allowed_divergence_points = tuple(
        str(point)
        for point in list(
            ((architecture_authority.get("fabric_taxonomy") or {}).get("allowed_divergence_points") or [])
        )
        if str(point).strip()
    )
    comparison = compare_reference_to_runtime(
        reference_result,
        runtime_summary,
        allowed_divergence_points=allowed_divergence_points,
    )
    surface_paths = _reference_compare_stable_surface_paths(lab_root=lab_root)
    authority_surface = _supplementary_surface_authority_surface("reference_compare", lab_root=lab_root)
    history_contract = str(
        authority_surface.get("source_history_contract")
        or "reference_compare_source_history_passthrough_v1"
    )
    today = dt.date.today().isoformat()
    history_payload = supplementary_surface_contract.build_latest_only_history_payload(
        history_contract=history_contract,
        history_path=str(surface_paths["history_path"]),
        latest_date=today,
        gate_ok=bool(comparison["gate_ok"]),
        freshness_mode="reference_compare_latest_only",
        entry_payload={
            "date": today,
            "status": comparison["status"],
            "gate_ok": comparison["gate_ok"],
            "gate_reasons": list(comparison.get("gate_reasons") or []),
            "allowed_divergence_points": list(comparison.get("allowed_divergence_points") or []),
            "invalid_divergence_points": list(comparison.get("invalid_divergence_points") or []),
        },
    )
    _write_json(surface_paths["history_path"], history_payload)

    report_payload = {
        **_artifact_metadata(
            role="reference_compare_surface_report",
            scope="reference_compare_only",
            producer="riscv_snn_lab.export_reference_compare_surface",
        ),
        "gate_name": "reference_model_runtime_compare",
        "gate_version": "1.0",
        "gate_ok": comparison["gate_ok"],
        "gate_reasons": list(comparison.get("gate_reasons") or []),
        "comparison": comparison,
        "runtime_summary": dict(runtime_summary),
        "stable_surfaces": {
            "report_path": str(surface_paths["report_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        },
        "history": history_payload,
    }
    _write_json(surface_paths["report_path"], report_payload)

    summary_md = supplementary_surface_contract.render_surface_summary_markdown(
        title="reference_compare nightly summary",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", comparison.get("status")),
            ("gate_ok", comparison.get("gate_ok")),
            ("gate_reasons", comparison.get("gate_reasons")),
            ("latest_date", history_payload.get("latest_date")),
            ("freshness_mode", history_payload.get("freshness_mode")),
            ("effective_all_dates_ok", history_payload.get("effective_all_dates_ok")),
            ("report_path", surface_paths["report_path"]),
            ("current_mainline_status_path", surface_paths["current_mainline_status_path"]),
            ("summary_md_path", surface_paths["summary_md_path"]),
        ],
    )
    _atomic_write_text(surface_paths["summary_md_path"], summary_md)

    current_status_md = supplementary_surface_contract.render_surface_current_status_markdown(
        title="reference_compare current status",
        generated_utc=report_payload["generated_utc"],
        role="non-blocking reference-model/runtime supplementary surface",
        sections=[
            (
                "Status",
                [
                    ("status", comparison.get("status")),
                    ("gate_ok", comparison.get("gate_ok")),
                    ("gate_reasons", comparison.get("gate_reasons")),
                ],
            ),
            (
                "Alignment",
                [
                    ("terminal_state_match", comparison.get("terminal_state_match")),
                    ("memory_domain_alignment", comparison.get("memory_domain_alignment")),
                    ("fabric_stage_alignment", comparison.get("fabric_stage_alignment")),
                    ("allowed_divergence_points", comparison.get("allowed_divergence_points")),
                    ("invalid_divergence_points", comparison.get("invalid_divergence_points")),
                ],
            ),
        ],
    )
    _atomic_write_text(surface_paths["current_mainline_status_path"], current_status_md)

    surface_payload = _normalize_supplementary_surface(
        "reference_compare",
        supplementary_surface_contract.build_surface_attachment(
            authority_surface=authority_surface,
            stable_surfaces=report_payload["stable_surfaces"],
            report_payload=report_payload,
            history_payload=history_payload,
        ),
        lab_root=lab_root,
    )

    sidecar_report = _load_json(sidecar_path)
    sidecar_report = supplementary_surface_contract.merge_supplementary_surface(
        sidecar_report=sidecar_report,
        name="reference_compare",
        surface_payload=surface_payload,
    )
    _write_json(sidecar_path, sidecar_report)

    return {
        **surface_payload,
        "status": comparison["status"],
    }


def _reference_program_compare_runtime_steps_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
) -> list[dict[str, Any]]:
    del family
    known_stages = {
        str(stage.get("name"))
        for stage in list(((architecture_authority.get("fabric_taxonomy") or {}).get("stages")) or [])
        if isinstance(stage, dict)
    }
    default_fabric_stages = [
        stage for stage in ["ingress_receive", "execution_consume"] if stage in known_stages
    ]
    divergence_points = _reference_compare_divergence_points_for_family(
        family_policy,
        architecture_authority=architecture_authority,
    )
    control_memory = ["ControlMemory"]

    if str(family_policy.get("timing_mode") or "") == "wfi_barrier_completion_visibility":
        return [
            {
                "step_name": "barrier_wait_visible",
                "terminal_state": "BarrierWaiting",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": [],
            },
            {
                "step_name": "completion_visible_after_wfi",
                "terminal_state": "Completed",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": divergence_points,
            },
        ]

    if str(family_policy.get("fault_lifecycle_mode") or "") == "clear_then_refault":
        return [
            {
                "step_name": "fault_visible",
                "terminal_state": "Faulted",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": divergence_points,
            },
            {
                "step_name": "fault_rearmed_visible",
                "terminal_state": "Faulted",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": divergence_points,
                "clear_fault_before_step": True,
            },
        ]

    if str(family_policy.get("fault_lifecycle_mode") or "") == "overwrite_chain":
        return [
            {
                "step_name": "fault_visible",
                "terminal_state": "Faulted",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": divergence_points,
            },
            {
                "step_name": "fault_overwrite_visible",
                "terminal_state": "Faulted",
                "memory_domains": control_memory,
                "fabric_stages": default_fabric_stages,
                "divergence_points": divergence_points,
                "overwrite_visible_fault_snapshot": True,
            },
        ]

    terminal_state = (
        "Faulted"
        if str(family_policy.get("fault_mode") or "") == "accepted_fault_required"
        else "Completed"
    )
    return [
        {
            "step_name": "program_step_0",
            "terminal_state": terminal_state,
            "memory_domains": control_memory,
            "fabric_stages": default_fabric_stages,
            "divergence_points": divergence_points,
        }
    ]


def _reference_program_compare_runtime_summary_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
) -> dict[str, Any]:
    steps = _reference_program_compare_runtime_steps_for_family(
        family,
        family_policy=family_policy,
        architecture_authority=architecture_authority,
    )
    completion_step_indices = [
        index
        for index, step in enumerate(steps)
        if str(step.get("terminal_state") or "") == "Completed"
    ]
    fault_step_indices = [
        index
        for index, step in enumerate(steps)
        if str(step.get("terminal_state") or "") == "Faulted"
    ]
    barrier_wait_step_indices = [
        index
        for index, step in enumerate(steps)
        if str(step.get("terminal_state") or "") == "BarrierWaiting"
    ]
    clear_fault_before_step_indices = [
        index for index, step in enumerate(steps) if bool(step.get("clear_fault_before_step"))
    ]
    overwrite_fault_step_indices = [
        index
        for index, step in enumerate(steps)
        if bool(step.get("overwrite_visible_fault_snapshot"))
    ]
    return {
        "family": family,
        "steps": steps,
        "step_count": len(steps),
        "terminal_state": str(steps[-1].get("terminal_state") or "Idle") if steps else "Idle",
        "terminal_states": [str(step.get("terminal_state") or "") for step in steps],
        "completion_step_indices": completion_step_indices,
        "fault_step_indices": fault_step_indices,
        "barrier_wait_step_indices": barrier_wait_step_indices,
        "clear_fault_before_step_indices": clear_fault_before_step_indices,
        "overwrite_fault_step_indices": overwrite_fault_step_indices,
        "fault_snapshot_sequence": [f"fault_step_{index}" for index in fault_step_indices],
    }


def _reference_program_compare_reference_result_for_runtime_summary(
    runtime_summary: dict[str, Any],
    *,
    machine: ReferenceMachine,
) -> Any:
    program_steps: list[ReferenceProgramStep] = []
    for step in list(runtime_summary.get("steps", []) or []):
        terminal_state = str(step.get("terminal_state") or "")
        if terminal_state == "Faulted":
            condition_values = {
                "fault_classified": True,
                "fault_csr_committed": True,
                "completion_suppressed_or_replaced_by_fault": True,
            }
        elif terminal_state == "Completed":
            condition_values = {
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": True,
                "no_higher_priority_fault_pending": True,
            }
        elif terminal_state == "BarrierWaiting":
            condition_values = {
                "architectural_state_committed": True,
                "local_outbound_handover_complete": True,
                "barrier_release_visible": False,
                "no_higher_priority_fault_pending": True,
            }
        else:
            raise ValueError(f"unsupported reference program terminal state: {terminal_state}")

        program_steps.append(
            ReferenceProgramStep(
                step_name=str(step.get("step_name") or f"program_step_{len(program_steps)}"),
                condition_values=condition_values,
                metadata={
                    "memory_domains": list(step.get("memory_domains", []) or []),
                    "fabric_stages": list(step.get("fabric_stages", []) or []),
                    "divergence_points": list(step.get("divergence_points", []) or []),
                },
                clear_fault_before_step=bool(step.get("clear_fault_before_step")),
                overwrite_visible_fault_snapshot=bool(
                    step.get("overwrite_visible_fault_snapshot")
                ),
            )
        )

    return machine.execute_program(
        ReferenceProgramRequest(
            family=str(runtime_summary.get("family") or "unknown"),
            steps=program_steps,
            metadata={"runtime_summary": dict(runtime_summary)},
        )
    )


def run_reference_program_compare_family(
    *,
    family: str,
    summary_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    architecture_authority = load_architecture_model_authority(lab_root=lab_root)
    source_input, source_input_path = _reference_program_primary_input_for_family(
        family,
        lab_root=lab_root,
    )
    request = _reference_program_request_for_family(
        family,
        family_policy=family_policy,
        architecture_authority=architecture_authority,
    )
    machine = ReferenceMachine.from_authority(architecture_authority)
    reference_result = machine.execute_program(request)
    allowed_divergence_points = tuple(
        str(point)
        for point in list(
            ((architecture_authority.get("fabric_taxonomy") or {}).get("allowed_divergence_points")) or []
        )
        if str(point).strip()
    )
    evidence_rows = _reference_program_evidence_rows_for_family(
        family=family,
        family_policy=family_policy,
        architecture_authority=architecture_authority,
        lab_root=lab_root,
    )
    source_rows: list[dict[str, Any]] = []
    gate_reasons: list[str] = []
    primary_runtime_summary: dict[str, Any] = {}
    primary_comparison: dict[str, Any] = {
        "status": "evidence_missing",
        "gate_ok": False,
        "gate_reasons": ["reference_program_evidence_missing"],
    }
    for index, evidence_row in enumerate(evidence_rows):
        runtime_summary = dict(evidence_row.get("runtime_program_summary") or {})
        if runtime_summary:
            comparison = compare_reference_program_to_runtime(
                reference_result,
                runtime_summary,
                allowed_divergence_points=allowed_divergence_points,
            )
        else:
            comparison = {
                "status": "evidence_missing",
                "gate_ok": False,
                "gate_reasons": [],
                "allowed_divergence_points": [],
                "invalid_divergence_points": [],
            }
        row_gate_reasons = [
            *list(evidence_row.get("evidence_gate_reasons") or []),
            *list(comparison.get("gate_reasons") or []),
        ]
        row_gate_ok = bool(evidence_row.get("evidence_ok")) and bool(comparison.get("gate_ok"))
        if row_gate_ok and comparison.get("status") == "allowed_divergence":
            row_status = "allowed_divergence"
        elif row_gate_ok:
            row_status = "aligned"
        elif evidence_row.get("evidence_ok") is not True:
            row_status = "evidence_missing"
        else:
            row_status = str(comparison.get("status") or "mismatch")
        source_row = {
            "source_kind": evidence_row.get("source_kind"),
            "source_origin": evidence_row.get("source_origin"),
            "program_name": evidence_row.get("program_name"),
            "evidence_source_path": evidence_row.get("evidence_source_path"),
            "evidence_ok": evidence_row.get("evidence_ok"),
            "evidence_gate_reasons": list(evidence_row.get("evidence_gate_reasons") or []),
            "status": row_status,
            "gate_ok": row_gate_ok,
            "gate_reasons": row_gate_reasons,
            "comparison": comparison,
            "runtime_program_summary": runtime_summary or None,
        }
        for optional_field in (
            "source_equiv_summary_path",
            "source_equiv_status",
            "source_matrix_path",
            "manifest_path",
        ):
            if optional_field in evidence_row:
                source_row[optional_field] = evidence_row.get(optional_field)
        source_rows.append(source_row)
        gate_reasons.extend(
            f"{source_row.get('source_kind')}:{reason}"
            for reason in row_gate_reasons
            if str(reason).strip()
        )
        if index == 0:
            primary_runtime_summary = runtime_summary
            primary_comparison = comparison

    overall_gate_ok = bool(source_rows) and all(bool(row.get("gate_ok")) for row in source_rows)
    if overall_gate_ok and any(row.get("status") == "allowed_divergence" for row in source_rows):
        status = "allowed_divergence"
    elif overall_gate_ok:
        status = "aligned"
    elif any(row.get("status") == "evidence_missing" for row in source_rows):
        status = "evidence_missing"
    else:
        status = "mismatch"
    resolved_summary_path = summary_path or default_reference_program_compare_family_summary_path(
        family,
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role="dated_reference_program_compare_family_surface",
            scope="reference_program_compare_only",
            producer="riscv_snn_lab.run_reference_program_compare_family",
        ),
        "family": family,
        "status": status,
        "gate_ok": overall_gate_ok,
        "gate_reasons": _sorted_unique(gate_reasons),
        "source_input_kind": source_input.get("source_kind"),
        "source_input_path": str(source_input_path),
        "source_input_status": source_input.get("status"),
        "runtime_policy": family_policy,
        "runtime_program_summary": primary_runtime_summary,
        "reference_terminal_states": list(reference_result.terminal_states),
        "comparison": primary_comparison,
        "evidence_rows": source_rows,
        "evidence_source_count": len(source_rows),
    }
    if source_input.get("source_kind") == "equiv_summary":
        summary["equiv_summary_path"] = str(source_input_path)
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    if source_input.get("source_kind") == "equiv_summary":
        summary["source_equiv_summary_path"] = str(source_input_path)
        summary["source_equiv_status"] = source_input.get("status")
    return summary


def run_reference_program_compare_matrix(
    *,
    families: list[str] | None = None,
    group: str = "all",
    summary_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    resolved_families = _resolve_reference_program_compare_families(
        families,
        group=group,
        lab_root=lab_root,
    )
    validation = validate_reference_program_profile_bindings(
        families=resolved_families,
        lab_root=lab_root,
    )
    if not validation["all_ok"]:
        raise ValueError(
            "invalid reference program profile bindings: "
            + ", ".join(validation["invalid_families"])
        )
    family_rows: list[dict[str, Any]] = []
    for family in resolved_families:
        family_summary = run_reference_program_compare_family(family=family, lab_root=lab_root)
        family_rows.append(
            {
                "family": family_summary["family"],
                "status": family_summary["status"],
                "gate_ok": family_summary["gate_ok"],
                "gate_reasons": list(family_summary.get("gate_reasons") or []),
                "summary_path": family_summary["summary_path"],
            }
        )
    resolved_summary_path = summary_path or default_reference_program_compare_matrix_summary_path(
        group=group,
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role="dated_reference_program_compare_matrix",
            scope="reference_program_compare_only",
            producer="riscv_snn_lab.run_reference_program_compare_matrix",
        ),
        "group": group,
        "count": len(family_rows),
        "all_ok": all(bool(row.get("gate_ok")) for row in family_rows),
        "gate_reasons": _sorted_unique(
            [reason for row in family_rows for reason in list(row.get("gate_reasons") or [])]
        ),
        "families": family_rows,
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def refresh_reference_program_compare_surface(
    *,
    families: list[str] | None = None,
    group: str = "all",
    sidecar_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
    refresh_derived_surfaces: bool = True,
) -> dict[str, Any]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    matrix_summary = run_reference_program_compare_matrix(
        families=families,
        group=group,
        lab_root=lab_root,
    )
    surface_paths = _reference_program_compare_stable_surface_paths(lab_root=lab_root)
    authority_surface = _supplementary_surface_authority_surface(
        "reference_program_compare",
        lab_root=lab_root,
    )
    status = "pass" if matrix_summary.get("all_ok") else "degraded"
    latest_date = dt.date.today().isoformat()
    history_payload = supplementary_surface_contract.build_latest_only_history_payload(
        history_contract=str(
            authority_surface.get("source_history_contract")
            or "reference_program_compare_source_history_passthrough_v1"
        ),
        history_path=str(surface_paths["history_path"]),
        latest_date=latest_date,
        gate_ok=bool(matrix_summary.get("all_ok")),
        freshness_mode="reference_program_compare_latest_only",
        entry_payload={
            "date": latest_date,
            "group": group,
            "count": matrix_summary.get("count"),
            "all_ok": matrix_summary.get("all_ok"),
            "gate_reasons": list(matrix_summary.get("gate_reasons") or []),
        },
    )
    _write_json(surface_paths["history_path"], history_payload)
    report_payload = {
        **_artifact_metadata(
            role="reference_program_compare_surface_report",
            scope="reference_program_compare_only",
            producer="riscv_snn_lab.refresh_reference_program_compare_surface",
        ),
        "gate_name": "reference_program_model_runtime_compare",
        "gate_version": "1.0",
        "gate_ok": bool(matrix_summary.get("all_ok")),
        "gate_reasons": list(matrix_summary.get("gate_reasons") or []),
        "status": status,
        "matrix_summary_path": matrix_summary.get("summary_path"),
        "group": group,
        "count": matrix_summary.get("count"),
        "families": list(matrix_summary.get("families") or []),
        "stable_surfaces": {
            "report_path": str(surface_paths["report_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        },
        "history": history_payload,
    }
    _write_json(surface_paths["report_path"], report_payload)
    summary_md = supplementary_surface_contract.render_surface_summary_markdown(
        title="reference_program_compare nightly summary",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", report_payload["gate_ok"]),
            ("group", group),
            ("count", matrix_summary.get("count")),
            ("matrix_summary_path", matrix_summary.get("summary_path")),
            ("latest_date", history_payload["latest_date"]),
            ("freshness_mode", history_payload["freshness_mode"]),
            ("effective_all_dates_ok", history_payload["effective_all_dates_ok"]),
            ("report_path", surface_paths["report_path"]),
            ("current_mainline_status_path", surface_paths["current_mainline_status_path"]),
        ],
    )
    _atomic_write_text(surface_paths["summary_md_path"], summary_md)
    current_status_md = supplementary_surface_contract.render_surface_current_status_markdown(
        title="reference_program_compare current status",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", report_payload["gate_ok"]),
            ("group", group),
            ("count", matrix_summary.get("count")),
            ("matrix_summary_path", matrix_summary.get("summary_path")),
        ],
    )
    _atomic_write_text(surface_paths["current_mainline_status_path"], current_status_md)

    surface_payload = _normalize_supplementary_surface(
        "reference_program_compare",
        supplementary_surface_contract.build_surface_attachment(
            authority_surface=authority_surface,
            stable_surfaces=report_payload["stable_surfaces"],
            report_payload=report_payload,
            history_payload=history_payload,
        ),
        lab_root=lab_root,
    )
    sidecar_report = supplementary_surface_contract.merge_supplementary_surface(
        sidecar_report=sidecar_report,
        name="reference_program_compare",
        surface_payload=surface_payload,
    )
    _write_json(resolved_sidecar_path, sidecar_report)

    if refresh_derived_surfaces:
        _refresh_derived_stable_surfaces(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
        )
    return {
        **surface_payload,
        "status": status,
        "count": matrix_summary.get("count"),
        "summary_path": matrix_summary.get("summary_path"),
    }


def refresh_stat_snapshot_family_surface(
    *,
    sidecar_path: Path | None = None,
    lab_root: Path = LAB_ROOT,
    refresh_derived_surfaces: bool = True,
    runner: Runner = run_command,
) -> dict[str, Any]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    selector_rows = _stat_snapshot_family_selector_rows(
        lab_root=lab_root,
        runner=runner,
    )
    selector_count = len(selector_rows)
    covered_selector_count = sum(1 for row in selector_rows if row.get("reference_ready"))
    gate_ok = selector_count > 0 and covered_selector_count == selector_count
    status = "pass" if gate_ok else "degraded"
    latest_date = dt.date.today().isoformat()
    surface_paths = _stat_snapshot_family_stable_surface_paths(lab_root=lab_root)
    authority_surface = _supplementary_surface_authority_surface("stat_snapshot_family", lab_root=lab_root)
    gate_reasons: list[str] = []
    for row in selector_rows:
        if row.get("reference_ready"):
            continue
        detail_parts: list[str] = []
        missing_assets = list(row.get("missing_assets") or [])
        if missing_assets:
            detail_parts.append(f"missing {','.join(missing_assets)}")
        validation_failures = list(row.get("validation_failures") or [])
        if validation_failures:
            detail_parts.append(f"validate {','.join(validation_failures)}")
        detail_text = "; ".join(detail_parts) if detail_parts else "not_ready"
        gate_reasons.append(f"selector:{row.get('selector_name')} {detail_text}")
    history_payload = supplementary_surface_contract.build_latest_only_history_payload(
        history_contract=str(
            authority_surface.get("source_history_contract") or "stat_snapshot_family_surface_history_v1"
        ),
        history_path=str(surface_paths["history_path"]),
        latest_date=latest_date,
        gate_ok=gate_ok,
        freshness_mode="latest_refresh_only",
        entry_payload={
            "date": latest_date,
            "selector_count": selector_count,
            "covered_selector_count": covered_selector_count,
            "gate_ok": gate_ok,
            "gate_reasons": gate_reasons,
        },
    )
    _write_json(surface_paths["history_path"], history_payload)
    report_payload = {
        **_artifact_metadata(
            role="stat_snapshot_family_surface_report",
            scope="stat_snapshot_family_only",
            producer="riscv_snn_lab.refresh_stat_snapshot_family_surface",
        ),
        "gate_name": "stat_snapshot_reference_coverage",
        "gate_version": "1.0",
        "gate_ok": gate_ok,
        "gate_reasons": gate_reasons,
        "status": status,
        "surface_contract": "stat_snapshot_family_surface_v1",
        "selector_count": selector_count,
        "covered_selector_count": covered_selector_count,
        "selector_rows": selector_rows,
        "stable_surfaces": {
            "report_path": str(surface_paths["report_path"]),
            "observer_summary_path": str(surface_paths["observer_summary_path"]),
            "summary_md_path": str(surface_paths["summary_md_path"]),
            "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        },
        "history": history_payload,
    }
    _write_json(surface_paths["report_path"], report_payload)
    summary_md = supplementary_surface_contract.render_surface_summary_markdown(
        title="stat_snapshot family nightly summary",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", gate_ok),
            ("selector_count", selector_count),
            ("covered_selector_count", covered_selector_count),
            ("latest_date", latest_date),
            ("freshness_mode", history_payload["freshness_mode"]),
            ("effective_all_dates_ok", history_payload["effective_all_dates_ok"]),
            ("report_path", surface_paths["report_path"]),
            ("current_mainline_status_path", surface_paths["current_mainline_status_path"]),
        ],
        extra_lines=[
            "- `{name}(selector={value}).reference_ready = {ready}`".format(
                name=row.get("selector_name"),
                value=row.get("selector_value"),
                ready=row.get("reference_ready"),
            )
            for row in selector_rows
        ],
    )
    _atomic_write_text(surface_paths["summary_md_path"], summary_md)
    current_status_md = supplementary_surface_contract.render_surface_current_status_markdown(
        title="stat_snapshot family current status",
        generated_utc=report_payload["generated_utc"],
        fields=[
            ("status", status),
            ("gate_ok", gate_ok),
            ("selector_count", selector_count),
            ("covered_selector_count", covered_selector_count),
        ],
        extra_lines=[
            "- `{name}.reference_ready = {ready}`".format(
                name=row.get("selector_name"),
                ready=row.get("reference_ready"),
            )
            for row in selector_rows
        ],
    )
    _atomic_write_text(surface_paths["current_mainline_status_path"], current_status_md)

    surface_payload = _normalize_supplementary_surface(
        "stat_snapshot_family",
        supplementary_surface_contract.build_surface_attachment(
            authority_surface=authority_surface,
            stable_surfaces=report_payload["stable_surfaces"],
            report_payload=report_payload,
            history_payload=history_payload,
            extra_fields={
                "surface_contract": report_payload["surface_contract"],
                "selector_rows": selector_rows,
                "selector_count": selector_count,
                "covered_selector_count": covered_selector_count,
            },
        ),
        lab_root=lab_root,
    )
    sidecar_report = supplementary_surface_contract.merge_supplementary_surface(
        sidecar_report=sidecar_report,
        name="stat_snapshot_family",
        surface_payload=surface_payload,
    )
    _write_json(resolved_sidecar_path, sidecar_report)

    if refresh_derived_surfaces:
        _refresh_derived_stable_surfaces(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
        )
    return {
        **surface_payload,
        "status": status,
        "summary_path": str(surface_paths["report_path"]),
    }


def _refresh_report_supplementary_surfaces(report: dict[str, Any], *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    refreshed_report = dict(report)
    merged_surfaces = _report_supplementary_surfaces(report, lab_root=lab_root)
    for name, payload in _supplementary_surfaces(lab_root=lab_root).items():
        merged_surfaces[name] = _normalize_supplementary_surface(name, payload, lab_root=lab_root)
    refreshed_report["supplementary_surfaces"] = merged_surfaces
    return refreshed_report


def _artifact_metadata(*,
                       role: str,
                       scope: str,
                       producer: str,
                       generated_utc: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_role": role,
        "authority_scope": scope,
        "producer": producer,
        "generated_utc": generated_utc or dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def default_equiv_summary_path(family: str,
                               *,
                               lab_root: Path = LAB_ROOT,
                               date_str: str | None = None) -> Path:
    stamp = date_str or dt.date.today().isoformat()
    return lab_root / "references" / f"{stamp}-{family.replace('_', '-')}-equiv.json"


def _normalized_surface_items(values: list[str]) -> list[str]:
    return sorted({value for value in values})


def _surface_label(canonical_surface: Any) -> str:
    return "canonical" if bool(canonical_surface) else "subset"


def _path_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "mtime_ns": None,
            "size": None,
        }
    stat = path.stat()
    return {
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _surface_digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _is_canonical_program_surface(group: str, programs: list[str]) -> bool:
    return _normalized_surface_items(programs) == _normalized_surface_items(matrix_programs(group))


def _default_matrix_summary_path(group: str,
                                 programs: list[str],
                                 *,
                                 lab_root: Path = LAB_ROOT) -> Path:
    if _is_canonical_program_surface(group, programs):
        return default_reference_path(f"{group}-regress-matrix", lab_root=lab_root)
    return default_reference_path(
        f"{group}-regress-matrix-subset-{_surface_digest(_normalized_surface_items(programs))}",
        lab_root=lab_root,
    )


def _default_audit_summary_path(group: str,
                                programs: list[str],
                                *,
                                lab_root: Path = LAB_ROOT) -> Path:
    if _is_canonical_program_surface(group, programs):
        return default_reference_path(f"{group}-bridge-audit", lab_root=lab_root)
    return default_reference_path(
        f"{group}-bridge-audit-subset-{_surface_digest(_normalized_surface_items(programs))}",
        lab_root=lab_root,
    )


def _is_canonical_nightly_surface(builder_programs: list[str], toolchain_programs: list[str]) -> bool:
    return (
        _is_canonical_program_surface("builder", builder_programs)
        and _is_canonical_program_surface("toolchain", toolchain_programs)
    )


def _default_nightly_summary_path(builder_programs: list[str],
                                  toolchain_programs: list[str],
                                  *,
                                  lab_root: Path = LAB_ROOT) -> Path:
    if _is_canonical_nightly_surface(builder_programs, toolchain_programs):
        return default_reference_path("nightly-index", lab_root=lab_root)
    return default_reference_path(
        "nightly-index-subset-"
        + _surface_digest(
            {
                "builder": _normalized_surface_items(builder_programs),
                "toolchain": _normalized_surface_items(toolchain_programs),
            }
        ),
        lab_root=lab_root,
    )


def _canonical_equiv_families(group: str, *, lab_root: Path = LAB_ROOT) -> list[str]:
    if group == "all":
        return list(EQUIV_MATRIX_GROUPS["all"])
    if group in _mainline_optional_groups(lab_root=lab_root):
        return _mainline_optional_group_families(group, lab_root=lab_root)
    raise ValueError(f"unknown equivalence matrix group: {group}")


def _is_canonical_equiv_surface(group: str,
                                families: list[str],
                                *,
                                lab_root: Path = LAB_ROOT) -> bool:
    return _normalized_surface_items(families) == _normalized_surface_items(
        _canonical_equiv_families(group, lab_root=lab_root)
    )


def _default_equiv_matrix_summary_path(group: str,
                                       families: list[str],
                                       *,
                                       lab_root: Path = LAB_ROOT) -> Path:
    canonical_name = "equiv-matrix" if group == "all" else f"equiv-matrix-{group.replace('_', '-')}"
    if _is_canonical_equiv_surface(group, families, lab_root=lab_root):
        return default_reference_path(canonical_name, lab_root=lab_root)
    return default_reference_path(
        f"{canonical_name}-subset-{_surface_digest(_normalized_surface_items(families))}",
        lab_root=lab_root,
    )


def toolchain_source_dir(program: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "firmware_src" / program


def _is_toolchain_program(program: str, *, lab_root: Path = LAB_ROOT) -> bool:
    return toolchain_source_dir(program, lab_root=lab_root).is_dir()


def _build_toolchain_program(program: str,
                             *,
                             lab_root: Path = LAB_ROOT,
                             runner: Runner = run_command) -> tuple[Path, Path]:
    toolchain_dir = toolchain_source_dir(program, lab_root=lab_root)
    if not toolchain_dir.exists():
        raise FileNotFoundError(f"missing toolchain source dir: {toolchain_dir}")

    elf = default_elf_path(program, lab_root=lab_root)
    spec = default_spec_path(program, lab_root=lab_root)
    if not spec.exists():
        raise FileNotFoundError(f"missing lab spec: {spec}")

    elf.parent.mkdir(parents=True, exist_ok=True)
    _ensure_success(runner(["make"], cwd=str(toolchain_dir)), f"build {program}")
    return elf, spec


def matrix_programs(group: str) -> list[str]:
    if group == "all":
        return [*PROGRAM_GROUPS["builder"], *PROGRAM_GROUPS["toolchain"]]
    try:
        return list(PROGRAM_GROUPS[group])
    except KeyError as exc:
        raise ValueError(f"unknown matrix group: {group}") from exc


def _suite_for_program(program: str, *, lab_root: Path = LAB_ROOT) -> str:
    return "toolchain" if _is_toolchain_program(program, lab_root=lab_root) else "builder"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return path


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        tmp_path.write_text(content, encoding=encoding)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def _write_json_text(path: Path, payload: dict[str, Any]) -> Path:
    return _atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def list_programs(*, runner: Runner = run_command, as_json: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["python3", str(GENERATOR_SCRIPT), "--list-programs"]
    if as_json:
        cmd.append("--json")
    return _ensure_success(runner(cmd), "list programs")


def _load_program_manifest(*, runner: Runner = run_command) -> dict[str, Any]:
    proc = list_programs(runner=runner, as_json=True)
    return json.loads(proc.stdout)


def _generator_overrides_from_existing_spec(spec_path: Path) -> list[str]:
    if not spec_path.exists():
        return []

    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    platform = dict(payload.get("platform", {}) or {})
    stop = dict(platform.get("stop", {}) or {})
    workload = dict(payload.get("workload", {}) or {})
    params = dict(workload.get("params", {}) or {})

    overrides: list[str] = []

    sim_time = stop.get("simulation_time")
    if sim_time is not None:
        overrides.extend(["--sim-time", str(sim_time)])

    mesh_size = platform.get("mesh_size")
    if mesh_size is not None:
        overrides.extend(["--mesh-size", str(mesh_size)])

    hart_isa = params.get("hart_isa")
    if hart_isa is not None:
        overrides.extend(["--hart-isa", str(hart_isa)])

    option_by_key = {
        "local_mem_bytes": "--local-mem-bytes",
        "cmd_queue_entries": "--cmd-queue-entries",
        "cmp_queue_entries": "--cmp-queue-entries",
        "rx_debug_queue_entries": "--rx-debug-queue-entries",
        "boot_addr": "--boot-addr",
    }
    for key, option in option_by_key.items():
        value = params.get(key)
        if value is None:
            continue
        overrides.extend([option, str(value)])

    return overrides


def generate_program(program: str,
                     *,
                     elf_path: Path | None = None,
                     spec_path: Path | None = None,
                     lab_root: Path = LAB_ROOT,
                     runner: Runner = run_command) -> tuple[Path, Path]:
    if _is_toolchain_program(program, lab_root=lab_root):
        default_elf = default_elf_path(program, lab_root=lab_root)
        default_spec = default_spec_path(program, lab_root=lab_root)
        if elf_path is not None and elf_path.resolve() != default_elf.resolve():
            raise ValueError("toolchain bridge programs use the lab-local default ELF path")
        if spec_path is not None and spec_path.resolve() != default_spec.resolve():
            raise ValueError("toolchain bridge programs use the lab-local default spec path")
        return _build_toolchain_program(program, lab_root=lab_root, runner=runner)

    elf = elf_path or default_elf_path(program, lab_root=lab_root)
    spec = spec_path or default_spec_path(program, lab_root=lab_root)
    elf.parent.mkdir(parents=True, exist_ok=True)
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec_overrides = _generator_overrides_from_existing_spec(spec)
    cmd = [
        "python3",
        str(GENERATOR_SCRIPT),
        "--program",
        program,
        *spec_overrides,
        "--elf",
        str(elf),
        "--spec",
        str(spec),
    ]
    _ensure_success(runner(cmd), f"generate {program}")
    return elf, spec


def validate_program(*,
                     program: str | None = None,
                     spec_path: Path | None = None,
                     lab_root: Path = LAB_ROOT,
                     runner: Runner = run_command) -> subprocess.CompletedProcess[str]:
    resolved_spec = _resolve_existing_spec(
        program=program,
        spec_path=spec_path,
        lab_root=lab_root,
        runner=runner,
        action="validate",
    )
    cmd = ["python3", str(SPEC_CLI), "validate", str(resolved_spec)]
    return _ensure_success(runner(cmd, cwd=str(SST_DRAM_SI_ROOT)), f"validate {resolved_spec}")


def _parse_run_dir(output: str) -> Path:
    match = re.search(r"\[mesh\] run complete: (.+)", output)
    if match:
        return Path(match.group(1).strip())
    summary_match = re.search(r"\[mesh\] summary written: (.+/essential_summary_mesh\.json)", output)
    if summary_match:
        return Path(summary_match.group(1).strip()).parent
    validation_match = re.search(r"\[val\]\s+SUMMARY\s+run_dir=([^\s]+)", output)
    if validation_match:
        return Path(validation_match.group(1).strip())
    raise RuntimeError("smoke output did not include run directory")


def _smoke_run_root_for_spec(spec_path: Path, *, lab_root: Path = LAB_ROOT) -> Path:
    return lab_root / "smoke_runs" / spec_path.stem


def _recover_latest_run_dir_from_root(run_root: Path) -> Path | None:
    if not run_root.exists():
        return None
    candidates = [
        path for path in run_root.iterdir()
        if path.is_dir() and (path / "essential_summary_mesh.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _binary_runnable(path: Path, *, runner: Runner = run_command) -> bool:
    proc = runner([str(path), "--version"])
    return proc.returncode == 0


def parallel_sst_preflight(*,
                           lab_root: Path = LAB_ROOT,
                           runner: Runner = run_command) -> dict[str, Any]:
    repo_root = lab_root.parent
    user_sst_bin = os.environ.get("SST_BIN")
    install_prefixes = [
        repo_root / "sst_install_mpi",
        repo_root / "sst_install",
        repo_root / "sst_install_serial",
    ]
    summary = {
        "reporting_scope": "research_only_nonblocking",
        "status": "skipped",
        "selected_bin": None,
        "reason_ids": [],
        "parallel_candidates_checked": [],
        "parallel_runnable_candidates": [],
        "user_override_bin": user_sst_bin or None,
        "mpi_bin": str(repo_root / "sst_install_mpi" / "bin" / "sst"),
        "parallel_bin": str(repo_root / "sst_install" / "bin" / "sst"),
        "serial_bin": str(repo_root / "sst_install_serial" / "bin" / "sst"),
    }
    if user_sst_bin:
        summary["status"] = "user_override"
        return summary
    if not any(prefix.exists() for prefix in install_prefixes):
        return summary

    mpi_bin = Path(summary["mpi_bin"])
    parallel_bin = Path(summary["parallel_bin"])
    serial_bin = Path(summary["serial_bin"])

    mpi_exists = _is_executable_file(mpi_bin)
    parallel_exists = _is_executable_file(parallel_bin)
    serial_exists = _is_executable_file(serial_bin)

    mpi_runnable = False
    parallel_runnable = False
    if mpi_exists:
        summary["parallel_candidates_checked"].append(str(mpi_bin))
        mpi_runnable = _binary_runnable(mpi_bin, runner=runner)
        if mpi_runnable:
            summary["parallel_runnable_candidates"].append(str(mpi_bin))
    if parallel_exists:
        summary["parallel_candidates_checked"].append(str(parallel_bin))
        parallel_runnable = _binary_runnable(parallel_bin, runner=runner)
        if parallel_runnable:
            summary["parallel_runnable_candidates"].append(str(parallel_bin))

    if mpi_runnable:
        summary["status"] = "ok"
        summary["selected_bin"] = str(mpi_bin)
        return summary
    if parallel_runnable:
        summary["status"] = "ok"
        summary["selected_bin"] = str(parallel_bin)
        return summary
    if parallel_exists:
        summary["status"] = "parallel_unavailable"
        summary["reason_ids"] = ["preflight_env_parallel_sst_unavailable"]
        return summary
    if mpi_exists:
        summary["status"] = "parallel_unavailable"
        summary["reason_ids"] = ["preflight_env_parallel_sst_unavailable"]
        return summary
    summary["status"] = "parallel_missing"
    if serial_exists:
        summary["reason_ids"] = ["preflight_env_parallel_sst_missing"]
        return summary
    summary["reason_ids"] = ["preflight_env_parallel_sst_missing"]
    return summary


def _format_parallel_sst_preflight_failure(summary: dict[str, Any], *, spec_path: Path) -> str:
    status = str(summary.get("status", "unknown"))
    mpi_bin = str(summary.get("mpi_bin") or "")
    parallel_bin = str(summary.get("parallel_bin") or "")
    serial_bin = str(summary.get("serial_bin") or "")
    checked = set(summary.get("parallel_candidates_checked", []))
    if status == "parallel_unavailable":
        blocking_bin = parallel_bin if parallel_bin in checked else mpi_bin
        return (
            f"parallel SST preflight failed for {spec_path}\n"
            f"[mesh] error: parallel SST exists but is not runnable in the current environment; "
            f"refusing to fall back to serial: {blocking_bin}"
        )
    if status == "parallel_missing" and serial_bin and Path(serial_bin).exists():
        return (
            f"parallel SST preflight failed for {spec_path}\n"
            f"[mesh] error: only serial SST is available; refusing to fall back from parallel to serial: {serial_bin}"
        )
    if status == "parallel_missing":
        return (
            f"parallel SST preflight failed for {spec_path}\n"
            "[mesh] error: no working parallel SST binary found (checked MPI and parallel installs); refusing to run."
        )
    return f"parallel SST preflight failed for {spec_path} (status={status})"


def ensure_parallel_sst_preflight(*,
                                  spec_path: Path,
                                  lab_root: Path = LAB_ROOT,
                                  runner: Runner = run_command) -> dict[str, Any]:
    summary = parallel_sst_preflight(lab_root=lab_root, runner=runner)
    if summary.get("status") in {"ok", "skipped", "user_override"}:
        return summary
    raise PreflightFailure(
        spec_path=spec_path,
        summary=summary,
        message=_format_parallel_sst_preflight_failure(summary, spec_path=spec_path),
    )


def _smoke_failure_reason_ids(error_message: str) -> list[str]:
    text = str(error_message)
    reason_ids: list[str] = []
    if "parallel SST exists but is not runnable" in text or "MPI SST exists but is not runnable" in text:
        reason_ids.append("smoke_env_parallel_sst_unavailable")
    if "only serial SST is available" in text:
        reason_ids.append("smoke_env_parallel_sst_missing")
    if "no working parallel SST binary found" in text:
        reason_ids.append("smoke_env_parallel_sst_missing")
    if "设备上没有空间" in text or "No space left on device" in text:
        reason_ids.append("smoke_env_run_root_no_space")
    if "failed before producing a run directory" in text:
        reason_ids.append("smoke_env_run_dir_missing")
    return sorted(set(reason_ids))


def _run_smoke_with_optional_failure(*,
                                     spec_path: Path,
                                     lab_root: Path = LAB_ROOT,
                                     runner: Runner = run_command,
                                     allow_failed_run: bool = False) -> tuple[Path, subprocess.CompletedProcess[str]]:
    resolved_spec = spec_path
    _ = ensure_runtime_bridge_build_guard(spec_path=resolved_spec, lab_root=lab_root)
    _ = validate_program(spec_path=resolved_spec, lab_root=lab_root, runner=runner)
    _ = ensure_parallel_sst_preflight(
        spec_path=resolved_spec,
        lab_root=lab_root,
        runner=runner,
    )
    smoke_run_root = _smoke_run_root_for_spec(resolved_spec, lab_root=lab_root)
    proc = runner(
        [
            "env",
            f"MESH_RUN_ROOT={smoke_run_root}",
            str(SMOKE_SCRIPT),
            "--spec",
            str(resolved_spec),
        ],
        cwd=str(SST_DRAM_SI_ROOT),
    )
    if proc.returncode == 0:
        return _parse_run_dir(proc.stdout), proc
    if not allow_failed_run:
        raise RuntimeError(f"smoke {resolved_spec} failed\n{proc.stdout}{proc.stderr}".strip())
    combined_output = f"{proc.stdout}{proc.stderr}"
    try:
        run_dir = _parse_run_dir(combined_output)
    except RuntimeError as exc:
        recovered_run_dir = _recover_latest_run_dir_from_root(smoke_run_root)
        if recovered_run_dir is not None:
            return recovered_run_dir, proc
        raise SmokeFailure(
            spec_path=resolved_spec,
            proc=proc,
            message=f"smoke {resolved_spec} failed before producing a run directory\n{combined_output}".strip(),
        ) from exc
    if not run_dir.exists():
        raise SmokeFailure(
            spec_path=resolved_spec,
            proc=proc,
            message=f"smoke {resolved_spec} failed and run directory is missing: {run_dir}",
            run_dir=run_dir,
        )
    return run_dir, proc


def smoke_program(program: str | None = None,
                  *,
                  spec_path: Path | None = None,
                  lab_root: Path = LAB_ROOT,
                  runner: Runner = run_command) -> Path:
    resolved_spec = spec_path
    if program:
        _, resolved_spec = generate_program(program, lab_root=lab_root, runner=runner)
    if resolved_spec is None:
        raise ValueError("smoke requires --program or --spec")
    run_dir, _ = _run_smoke_with_optional_failure(
        spec_path=resolved_spec,
        lab_root=lab_root,
        runner=runner,
        allow_failed_run=False,
    )
    return run_dir


def run_protocol_suite(suite: str = "all",
                       *,
                       runner: Runner = run_command) -> subprocess.CompletedProcess[str]:
    target_by_suite = {
        "all": "test-riscv-snn-protocols",
        "builder": "test-riscv-snn-firmware-protocol",
        "toolchain": "test-riscv-snn-toolchain-firmware-protocol",
    }
    try:
        target = target_by_suite[suite]
    except KeyError as exc:
        raise ValueError(f"unknown protocol suite: {suite}") from exc
    return _ensure_success(
        runner(["make", target], cwd=str(SNNDL_ROOT)),
        f"protocol suite {suite}",
    )


def run_regression(program: str,
                   *,
                   suite: str = "all",
                   register: bool = False,
                   manifest_path: Path | None = None,
                   sample_manifest: dict[str, Any] | None = None,
                   lab_root: Path = LAB_ROOT,
                   runner: Runner = run_command) -> tuple[Path, Path | None]:
    _ = run_protocol_suite(suite, runner=runner)
    run_dir = smoke_program(program, lab_root=lab_root, runner=runner)
    resolved_manifest_path = None
    if register:
        manifest_manifest = sample_manifest
        if manifest_manifest is None:
            manifest_manifest = _load_program_manifest(runner=runner)
        resolved_manifest_path = register_run(
            program,
            run_dir,
            manifest_path=manifest_path,
            lab_root=lab_root,
            sample_manifest=manifest_manifest,
        )
    return run_dir, resolved_manifest_path


def run_matrix(group: str = "all",
               *,
               programs: list[str] | None = None,
               register: bool = False,
               summary_path: Path | None = None,
               lab_root: Path = LAB_ROOT,
               runner: Runner = run_command) -> dict[str, Any]:
    resolved_programs = list(programs) if programs is not None else matrix_programs(group)
    canonical_surface = _is_canonical_program_surface(group, resolved_programs)
    sample_manifest = _load_program_manifest(runner=runner) if register else None
    suites = { _suite_for_program(program, lab_root=lab_root) for program in resolved_programs }
    for suite in sorted(suites):
        run_protocol_suite(suite, runner=runner)
    results: list[dict[str, Any]] = []
    for program in resolved_programs:
        suite = _suite_for_program(program, lab_root=lab_root)
        run_dir = smoke_program(program, lab_root=lab_root, runner=runner)
        manifest_path = None
        if register:
            manifest_path = register_run(
                program,
                run_dir,
                manifest_path=None,
                lab_root=lab_root,
                sample_manifest=sample_manifest,
            )
        results.append(
            {
                "program": program,
                "suite": suite,
                "run_dir": str(run_dir),
                "manifest_path": str(manifest_path) if manifest_path else None,
            }
        )

    resolved_summary_path = summary_path or _default_matrix_summary_path(
        group,
        resolved_programs,
        lab_root=lab_root,
    )
    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "group": group,
        "count": len(results),
        "register": register,
        "canonical_surface": canonical_surface,
        "requested_programs": resolved_programs,
        "results": results,
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_authority_path(*, lab_root: Path, default_path: Path) -> Path:
    if lab_root == LAB_ROOT:
        return default_path
    candidate = lab_root / "spec_authority" / default_path.name
    return candidate if candidate.exists() else default_path


def load_mainline_gate_authority(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    return _load_json(_resolve_authority_path(lab_root=lab_root, default_path=MAINLINE_GATE_AUTHORITY_PATH))


def load_runtime_gate_authority(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    return _load_json(_resolve_authority_path(lab_root=lab_root, default_path=RUNTIME_GATE_AUTHORITY_PATH))


def load_accel_authority(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    return _load_json(_resolve_authority_path(lab_root=lab_root, default_path=ACCEL_AUTHORITY_PATH))


def load_architecture_model_authority(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    authority = _load_json(
        _resolve_authority_path(
            lab_root=lab_root,
            default_path=ARCHITECTURE_MODEL_AUTHORITY_PATH,
        )
    )
    if int(authority.get("schema_version", 0) or 0) != 1:
        raise ValueError("unsupported architecture model authority schema")
    return authority


def load_supplementary_surface_authority(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    authority = _load_json(
        _resolve_authority_path(
            lab_root=lab_root,
            default_path=SUPPLEMENTARY_SURFACE_AUTHORITY_PATH,
        )
    )
    if int(authority.get("schema_version", 0) or 0) != 1:
        raise ValueError("unsupported supplementary surface authority schema")
    return authority


def _supplementary_surface_authority_surface(
    name: str,
    *,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    authority = load_supplementary_surface_authority(lab_root=lab_root)
    surfaces = dict(authority.get("surfaces") or {})
    surface = surfaces.get(name)
    return dict(surface) if isinstance(surface, dict) else {}


def _supplementary_surface_contract_issues(
    name: str,
    payload: dict[str, Any],
    *,
    lab_root: Path = LAB_ROOT,
) -> list[str]:
    policy = _supplementary_surface_authority_surface(name, lab_root=lab_root)
    issues: list[str] = []
    if not policy:
        return issues
    expected_surface_kind = str(policy.get("surface_kind") or "").strip()
    if expected_surface_kind and str(payload.get("surface_kind") or "") != expected_surface_kind:
        issues.append("contract.surface_kind")
    if "blocking" in policy and bool(payload.get("blocking")) is not bool(policy.get("blocking")):
        issues.append("contract.blocking")
    for field in list(policy.get("required_surface_fields") or []):
        if payload.get(str(field)) is None:
            issues.append(f"contract.missing_field:{field}")
    return issues


def _runtime_gate_family_policies(*, lab_root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    authority = load_runtime_gate_authority(lab_root=lab_root)
    return {
        str(family): dict(policy)
        for family, policy in dict(authority.get("families", {}) or {}).items()
    }


def _runtime_gate_family_policy(family: str, *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    policies = _runtime_gate_family_policies(lab_root=lab_root)
    if family not in policies:
        raise ValueError(f"unknown runtime gate family: {family}")
    return dict(policies[family])


def _reference_program_compare_family_names(*, lab_root: Path = LAB_ROOT) -> tuple[str, ...]:
    policies = _runtime_gate_family_policies(lab_root=lab_root)
    families = [
        family
        for family, policy in sorted(policies.items())
        if str(policy.get("reference_program_profile") or "").strip()
    ]
    return tuple(families)


def _reference_program_compare_group_names(*, lab_root: Path = LAB_ROOT) -> tuple[str, ...]:
    return tuple(["all", *sorted(_mainline_optional_groups(lab_root=lab_root))])


def _reference_program_request_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
) -> ReferenceProgramRequest:
    model = ProgramProfileModel.from_authority(architecture_authority)
    return model.build_request(
        family=family,
        profile_name=str(family_policy.get("reference_program_profile") or ""),
        family_policy=family_policy,
    )


def _reference_program_runtime_summary_from_request(
    request: ReferenceProgramRequest,
) -> dict[str, Any]:
    return runtime_summary_from_program_request(request)


def _missing_reference_program_evidence(
    *,
    family: str,
    profile_name: str,
    source_kind: str,
    source_origin: str,
    reason: str,
    program_name: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "program_name": program_name or family,
        "reference_program_profile": profile_name,
        "source_kind": source_kind,
        "source_origin": source_origin,
        "evidence_source_path": source_path,
        "evidence_contract_name": None,
        "evidence_contract_version": None,
        "summary_sections_present": [],
        "missing_artifacts": [],
        "missing_summary_sections": [],
        "runtime_stats": {},
        "missing_runtime_stats": [],
        "validation": {"summary": "not_run", "pass_lines": [], "warn_lines": [], "fail_lines": []},
        "meta": {},
        "input_spec": {},
        "control_event_observations": [],
        "evidence_ok": False,
        "evidence_gate_reasons": [reason],
        "runtime_program_summary": None,
    }


def _reference_program_manifest_evidence_for_program(
    *,
    family: str,
    program_name: str,
    profile_name: str,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
    source_kind: str,
    source_origin: str,
    missing_reason: str,
    run_dir_missing_reason: str,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    manifest_path = _latest_manifest_path(program_name, lab_root=lab_root)
    if manifest_path is None:
        return _missing_reference_program_evidence(
            family=family,
            profile_name=profile_name,
            source_kind=source_kind,
            source_origin=source_origin,
            reason=missing_reason,
            program_name=program_name,
        )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    run_dir = _parse_manifest_run_dir(manifest_text)
    if not run_dir:
        return {
            **_missing_reference_program_evidence(
                family=family,
                profile_name=profile_name,
                source_kind=source_kind,
                source_origin=source_origin,
                reason=run_dir_missing_reason,
                program_name=program_name,
            ),
            "manifest_path": str(manifest_path),
        }

    evidence = ProgramEvidenceModel.from_authority(architecture_authority).extract_from_run_dir(
        family=family,
        profile_name=profile_name,
        family_policy=family_policy,
        run_dir=Path(str(run_dir)),
        source_kind=source_kind,
        source_origin=source_origin,
        program_name=program_name,
    )
    evidence["manifest_path"] = str(manifest_path)
    return evidence


def _latest_toolchain_regress_matrix_input(
    *,
    lab_root: Path = LAB_ROOT,
) -> tuple[dict[str, Any] | None, Path | None]:
    summary_path = _latest_dated_reference("*-toolchain-regress-matrix.json", lab_root=lab_root)
    if summary_path is None or not summary_path.exists():
        return None, None
    payload = _load_json(summary_path)
    payload.setdefault("summary_path", str(summary_path))
    return payload, summary_path


def _reference_program_runtime_bridge_evidence_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    equiv_summary, equiv_summary_path = _latest_reference_compare_family_input(family, lab_root=lab_root)
    runtime_bridge = dict(equiv_summary.get("runtime_bridge") or {})
    run_dir = runtime_bridge.get("run_dir")
    profile_name = str(family_policy.get("reference_program_profile") or "")
    if not run_dir:
        return {
            **_missing_reference_program_evidence(
                family=family,
                profile_name=profile_name,
                source_kind="runtime_bridge_run_dir",
                source_origin="runtime_bridge_equiv",
                reason="runtime_bridge_run_dir_missing",
                program_name=family,
            ),
            "source_equiv_summary_path": str(equiv_summary_path),
        }

    evidence = ProgramEvidenceModel.from_authority(architecture_authority).extract_from_run_dir(
        family=family,
        profile_name=profile_name,
        family_policy=family_policy,
        run_dir=Path(str(run_dir)),
        source_kind="runtime_bridge_run_dir",
        source_origin="runtime_bridge_equiv",
        program_name=family,
    )
    evidence["source_equiv_summary_path"] = str(equiv_summary_path)
    evidence["source_equiv_status"] = equiv_summary.get("status")
    return evidence


def _reference_program_toolchain_evidence_for_family(
    family: str,
    *,
    family_policy: dict[str, Any],
    architecture_authority: dict[str, Any],
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any] | None:
    toolchain_program = f"{family}_toolchain"
    if toolchain_program not in set(matrix_programs("toolchain")):
        return None
    if not toolchain_source_dir(toolchain_program, lab_root=lab_root).exists():
        return None

    profile_name = str(family_policy.get("reference_program_profile") or "")
    matrix_summary, matrix_summary_path = _latest_toolchain_regress_matrix_input(lab_root=lab_root)
    if matrix_summary is None or matrix_summary_path is None:
        return _missing_reference_program_evidence(
            family=family,
            profile_name=profile_name,
            source_kind="toolchain_run_dir",
            source_origin="toolchain_regress_matrix",
            reason="toolchain_regress_matrix_missing",
            program_name=toolchain_program,
        )

    toolchain_entry = _result_map_by_family(list(matrix_summary.get("results", []) or [])).get(family)
    if toolchain_entry is None:
        return {
            **_missing_reference_program_evidence(
                family=family,
                profile_name=profile_name,
                source_kind="toolchain_run_dir",
                source_origin="toolchain_regress_matrix",
                reason="toolchain_family_entry_missing",
                program_name=toolchain_program,
            ),
            "source_matrix_path": str(matrix_summary_path),
        }
    run_dir = toolchain_entry.get("run_dir")
    if not run_dir:
        return {
            **_missing_reference_program_evidence(
                family=family,
                profile_name=profile_name,
                source_kind="toolchain_run_dir",
                source_origin="toolchain_regress_matrix",
                reason="toolchain_run_dir_missing",
                program_name=str(toolchain_entry.get("program") or toolchain_program),
            ),
            "source_matrix_path": str(matrix_summary_path),
        }

    evidence = ProgramEvidenceModel.from_authority(architecture_authority).extract_from_run_dir(
        family=family,
        profile_name=profile_name,
        family_policy=family_policy,
        run_dir=Path(str(run_dir)),
        source_kind="toolchain_run_dir",
        source_origin="toolchain_regress_matrix",
        program_name=str(toolchain_entry.get("program") or toolchain_program),
    )
    evidence["source_matrix_path"] = str(matrix_summary_path)
    evidence["manifest_path"] = toolchain_entry.get("manifest_path")
    return evidence


def _reference_program_evidence_rows_for_family(
    *,
    family: str,
    family_policy: dict[str, Any] | None = None,
    architecture_authority: dict[str, Any] | None = None,
    lab_root: Path = LAB_ROOT,
) -> list[dict[str, Any]]:
    resolved_family_policy = (
        dict(family_policy)
        if family_policy is not None
        else _runtime_gate_family_policy(family, lab_root=lab_root)
    )
    resolved_architecture_authority = (
        dict(architecture_authority)
        if architecture_authority is not None
        else load_architecture_model_authority(lab_root=lab_root)
    )
    profile_name = str(resolved_family_policy.get("reference_program_profile") or "")
    if family not in EQUIV_FAMILY_SPECS:
        rows = [
            _reference_program_manifest_evidence_for_program(
                family=family,
                program_name=family,
                profile_name=profile_name,
                family_policy=resolved_family_policy,
                architecture_authority=resolved_architecture_authority,
                source_kind="runtime_bridge_run_dir",
                source_origin="runtime_manifest",
                missing_reason="runtime_manifest_missing",
                run_dir_missing_reason="runtime_manifest_run_dir_missing",
                lab_root=lab_root,
            )
        ]
        toolchain_program = f"{family}_toolchain"
        if (
            toolchain_source_dir(toolchain_program, lab_root=lab_root).exists()
            or default_spec_path(toolchain_program, lab_root=lab_root).exists()
        ):
            rows.append(
                _reference_program_manifest_evidence_for_program(
                    family=family,
                    program_name=toolchain_program,
                    profile_name=profile_name,
                    family_policy=resolved_family_policy,
                    architecture_authority=resolved_architecture_authority,
                    source_kind="toolchain_run_dir",
                    source_origin="toolchain_manifest",
                    missing_reason="toolchain_manifest_missing",
                    run_dir_missing_reason="toolchain_manifest_run_dir_missing",
                    lab_root=lab_root,
                )
            )
        return rows

    rows = [
        _reference_program_runtime_bridge_evidence_for_family(
            family,
            family_policy=resolved_family_policy,
            architecture_authority=resolved_architecture_authority,
            lab_root=lab_root,
        )
    ]
    toolchain_row = _reference_program_toolchain_evidence_for_family(
        family,
        family_policy=resolved_family_policy,
        architecture_authority=resolved_architecture_authority,
        lab_root=lab_root,
    )
    if toolchain_row is not None:
        rows.append(toolchain_row)
    return rows


def validate_reference_program_profile_bindings(
    *,
    families: list[str] | None = None,
    lab_root: Path = LAB_ROOT,
) -> dict[str, Any]:
    resolved_families = list(families) if families is not None else sorted(EQUIV_FAMILY_SPECS)
    architecture_authority = load_architecture_model_authority(lab_root=lab_root)
    rows: list[dict[str, Any]] = []
    invalid_families: list[str] = []
    for family in resolved_families:
        family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
        try:
            request = _reference_program_request_for_family(
                family,
                family_policy=family_policy,
                architecture_authority=architecture_authority,
            )
            row = {
                "family": family,
                "reference_program_profile": str(
                    family_policy.get("reference_program_profile") or ""
                ),
                "step_count": len(request.steps),
                "step_names": [step.step_name for step in request.steps],
                "valid": True,
            }
        except ValueError as exc:
            row = {
                "family": family,
                "reference_program_profile": str(
                    family_policy.get("reference_program_profile") or ""
                ),
                "valid": False,
                "error": str(exc),
            }
            invalid_families.append(family)
        rows.append(row)

    return {
        "all_ok": not invalid_families,
        "rows": rows,
        "invalid_families": invalid_families,
    }


def _runtime_gate_reason_ids(*, lab_root: Path = LAB_ROOT) -> list[str]:
    return list(load_runtime_gate_authority(lab_root=lab_root).get("reason_ids", []))


def _runtime_gate_check_ids(*, lab_root: Path = LAB_ROOT) -> list[str]:
    return list(load_runtime_gate_authority(lab_root=lab_root).get("check_ids", []))


def _runtime_gate_check_catalog(*, lab_root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    authority = load_runtime_gate_authority(lab_root=lab_root)
    return {
        str(check_id): dict(payload)
        for check_id, payload in dict(authority.get("checks", {}) or {}).items()
    }


def _runtime_gate_reason_catalog(*, lab_root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    authority = load_runtime_gate_authority(lab_root=lab_root)
    return {
        str(reason_id): dict(payload)
        for reason_id, payload in dict(authority.get("reasons", {}) or {}).items()
    }


EQUIV_FAMILY_POLICIES = _runtime_gate_family_policies()


def _mainline_optional_group_families(group: str, *, lab_root: Path = LAB_ROOT) -> list[str]:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    optional_groups = authority.get("optional_groups", {})
    group_payload = optional_groups.get(group)
    if not isinstance(group_payload, dict):
        raise ValueError(f"unknown equivalence matrix group: {group}")
    return list(group_payload.get("families", []))


def _mainline_optional_groups(*, lab_root: Path = LAB_ROOT) -> dict[str, dict[str, Any]]:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    return {
        str(group): dict(payload or {})
        for group, payload in dict(authority.get("optional_groups", {}) or {}).items()
        if isinstance(payload, dict)
    }


def _mainline_optional_group_promotion_contract(group: str, *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    return dict((authority.get("promotion_contract", {}) or {}).get(group, {}) or {})


def _optional_history_refresh_mode(group: str, *, lab_root: Path = LAB_ROOT) -> str:
    freshness_mode = str(
        _mainline_optional_group_promotion_contract(group, lab_root=lab_root).get(
            "multi_date_freshness_mode"
        )
        or "all_dates"
    )
    if freshness_mode == "since_latest_recovery":
        return "compact_latest_recovery"
    return "dated_scan"


def _mainline_defaults(*, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    return dict(authority.get("mainline_defaults") or {})


def _resolve_mainline_optional_group_default(key: str, *, lab_root: Path = LAB_ROOT) -> str | None:
    optional_groups = _mainline_optional_groups(lab_root=lab_root)
    if not optional_groups:
        return None
    defaults = _mainline_defaults(lab_root=lab_root)
    candidate = defaults.get(key)
    if isinstance(candidate, str) and candidate in optional_groups:
        return candidate
    if "queue_optional" in optional_groups:
        return "queue_optional"
    return sorted(optional_groups)[0]


def _mainline_primary_optional_group(*, lab_root: Path = LAB_ROOT) -> str | None:
    return _resolve_mainline_optional_group_default("primary_optional_group", lab_root=lab_root)


def _mainline_refresh_default_group(*, lab_root: Path = LAB_ROOT) -> str | None:
    return _resolve_mainline_optional_group_default("mainline_refresh_default_group", lab_root=lab_root)


def _ordered_optional_groups(group_names: list[str], *, primary_group: str | None) -> list[str]:
    unique_groups = sorted({str(group) for group in group_names})
    if primary_group is None or primary_group not in unique_groups:
        return unique_groups
    return [primary_group, *[group for group in unique_groups if group != primary_group]]


def _optional_group_has_visible_state(group: str,
                                      *,
                                      optional_group_rollups: dict[str, dict[str, Any]],
                                      optional_admission_surfaces: dict[str, dict[str, Any]],
                                      optional_admission_paths: dict[str, Path]) -> bool:
    rollup = dict(optional_group_rollups.get(group) or {})
    admission = dict(optional_admission_surfaces.get(group) or {})
    admission_path = optional_admission_paths.get(group)
    return bool(rollup.get("enabled")) or bool(admission) or admission_path is not None


def _active_optional_group(group_names: list[str],
                           *,
                           primary_group: str | None,
                           optional_group_rollups: dict[str, dict[str, Any]],
                           optional_admission_surfaces: dict[str, dict[str, Any]],
                           optional_admission_paths: dict[str, Path]) -> str | None:
    ordered_groups = _ordered_optional_groups(group_names, primary_group=primary_group)
    if primary_group and _optional_group_has_visible_state(
        primary_group,
        optional_group_rollups=optional_group_rollups,
        optional_admission_surfaces=optional_admission_surfaces,
        optional_admission_paths=optional_admission_paths,
    ):
        return primary_group
    for group in ordered_groups:
        if _optional_group_has_visible_state(
            group,
            optional_group_rollups=optional_group_rollups,
            optional_admission_surfaces=optional_admission_surfaces,
            optional_admission_paths=optional_admission_paths,
        ):
            return group
    if primary_group is not None:
        return primary_group
    return ordered_groups[0] if ordered_groups else None


def _report_optional_group_surfaces(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    optional_group_surfaces = {
        str(group): dict(payload or {})
        for group, payload in dict(report.get("optional_group_surfaces", {}) or {}).items()
        if isinstance(payload, dict)
    }
    queue_equivalence = dict(report.get("queue_equivalence") or {})
    if queue_equivalence and "queue_optional" not in optional_group_surfaces:
        optional_group_surfaces["queue_optional"] = queue_equivalence
    return optional_group_surfaces


def _refresh_report_optional_group_surfaces(report: dict[str, Any], *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    refreshed_report = dict(report)
    optional_group_surfaces = _report_optional_group_surfaces(report)
    groups = _sorted_unique([*(report.get("with_optional_groups") or []), *optional_group_surfaces.keys()])
    if not groups:
        return refreshed_report

    refreshed_optional_group_surfaces = dict(optional_group_surfaces)
    changed = False
    for group in groups:
        latest_surface, latest_path = _latest_optional_group_equivalence_surface(
            group=group,
            lab_root=lab_root,
        )
        if latest_surface is None:
            continue
        latest_payload = dict(latest_surface)
        if latest_path is not None:
            latest_payload.setdefault("summary_path", str(latest_path))
        current_payload = dict(refreshed_optional_group_surfaces.get(group) or {})
        current_key = (
            _optional_surface_freshness_key(current_payload)
            if current_payload
            else ("", float("-inf"), float("-inf"))
        )
        latest_key = _optional_surface_freshness_key(
            latest_payload,
            summary_path=str(latest_path) if latest_path is not None else latest_payload.get("summary_path"),
        )
        if not current_payload or latest_key > current_key or (
            latest_key == current_key and latest_payload != current_payload
        ):
            refreshed_optional_group_surfaces[group] = latest_payload
            changed = changed or latest_payload != current_payload

    if not changed and "optional_group_surfaces" in refreshed_report:
        return refreshed_report

    refreshed_report["optional_group_surfaces"] = refreshed_optional_group_surfaces
    queue_equivalence = dict(refreshed_optional_group_surfaces.get("queue_optional") or {})
    if queue_equivalence or refreshed_report.get("with_queue_equivalence") or refreshed_report.get("queue_equivalence"):
        refreshed_report["queue_equivalence"] = queue_equivalence or None
    return refreshed_report


def _observer_summary_optional_group_rollups(observer_summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = observer_summary or {}
    optional_group_rollups = {
        str(group): dict(row or {})
        for group, row in dict(payload.get("optional_group_rollups", {}) or {}).items()
        if isinstance(row, dict)
    }
    queue_rollup = dict((((payload.get("optional_surfaces") or {}).get("queue_equivalence")) or {}))
    if queue_rollup and "queue_optional" not in optional_group_rollups:
        optional_group_rollups["queue_optional"] = queue_rollup
    return optional_group_rollups


def _equiv_matrix_group_names(*, lab_root: Path = LAB_ROOT) -> tuple[str, ...]:
    return tuple(["all", *sorted(_mainline_optional_groups(lab_root=lab_root))])


def _optional_group_singleton_family(group: str, *, lab_root: Path = LAB_ROOT) -> str | None:
    families = _mainline_optional_group_families(group, lab_root=lab_root)
    if len(families) != 1:
        return None
    return str(families[0])


def _optional_group_matrix_pattern(group: str) -> str:
    return f"*-equiv-matrix-{group.replace('_', '-')}.json"


def _optional_group_family_equiv_pattern(family: str) -> str:
    return f"*-{family.replace('_', '-')}-equiv.json"


def _optional_group_has_dated_inputs(group: str, *, lab_root: Path = LAB_ROOT) -> bool:
    refs_dir = lab_root / "references"
    if any(refs_dir.glob(_optional_group_matrix_pattern(group))):
        return True
    singleton_family = _optional_group_singleton_family(group, lab_root=lab_root)
    if singleton_family is None:
        return False
    return any(refs_dir.glob(_optional_group_family_equiv_pattern(singleton_family)))


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _extract_mesh_stat_totals(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    totals: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = row.get("StatisticName", "")
            if not name:
                continue
            value = row.get("Sum.u64") or row.get("Sum.f64") or "0"
            try:
                totals[name] = totals.get(name, 0.0) + float(value)
            except ValueError:
                continue
    return totals


def _latest_manifest_path(program: str, *, lab_root: Path = LAB_ROOT) -> Path | None:
    candidates = sorted(
        path for path in (lab_root / "runs").glob(f"*-{program.replace('_', '-')}-*.md") if path.is_file()
    )
    return candidates[-1] if candidates else None


def _parse_manifest_asset(content: str, label: str) -> dict[str, Any] | None:
    match = re.search(
        rf"- {re.escape(label)}：\s*\n  - path：`([^`]+)`\s*\n  - sha256：`([0-9a-f]+)`\s*\n  - bytes：`(\d+)`",
        content,
        flags=re.S,
    )
    if not match:
        return None
    return {
        "path": match.group(1),
        "sha256": match.group(2),
        "bytes": int(match.group(3)),
    }


def _parse_manifest_run_dir(content: str) -> str | None:
    match = re.search(r"- 历史 run dir：`([^`]+)`", content)
    return match.group(1) if match else None


def _audit_program(program: str, *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    elf_path = default_elf_path(program, lab_root=lab_root)
    spec_path = default_spec_path(program, lab_root=lab_root)
    source_dir = toolchain_source_dir(program, lab_root=lab_root)
    manifest_path = _latest_manifest_path(program, lab_root=lab_root)

    elf_exists = elf_path.exists()
    spec_exists = spec_path.exists()
    is_toolchain = source_dir.is_dir()
    source_files = [
        _file_info(path)
        for path in sorted(path for path in source_dir.rglob("*") if path.is_file())
    ] if is_toolchain else []

    manifest_elf_match = False
    manifest_spec_match = False
    manifest_run_dir = None
    if manifest_path is not None:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest_elf = _parse_manifest_asset(manifest_text, "Firmware ELF")
        manifest_spec = _parse_manifest_asset(manifest_text, "Replay spec JSON")
        manifest_run_dir = _parse_manifest_run_dir(manifest_text)
        if manifest_elf and elf_exists:
            manifest_elf_match = manifest_elf["sha256"] == _sha256(elf_path)
        if manifest_spec and spec_exists:
            manifest_spec_match = manifest_spec["sha256"] == _sha256(spec_path)

    ok = elf_exists and spec_exists and manifest_elf_match and manifest_spec_match
    if is_toolchain:
        ok = ok and bool(source_files)

    result = {
        "program": program,
        "suite": _suite_for_program(program, lab_root=lab_root),
        "is_toolchain": is_toolchain,
        "source_dir": str(source_dir) if is_toolchain else None,
        "source_file_count": len(source_files),
        "source_files": source_files,
        "elf": _file_info(elf_path) if elf_exists else None,
        "spec": _file_info(spec_path) if spec_exists else None,
        "latest_manifest": str(manifest_path) if manifest_path else None,
        "manifest_run_dir": manifest_run_dir,
        "manifest_elf_match": manifest_elf_match,
        "manifest_spec_match": manifest_spec_match,
        "manifest_match": manifest_elf_match and manifest_spec_match,
        "ok": ok,
    }
    return result


def audit_programs(group: str = "all",
                   *,
                   programs: list[str] | None = None,
                   protocol: bool = False,
                   summary_path: Path | None = None,
                   lab_root: Path = LAB_ROOT,
                   runner: Runner = run_command) -> dict[str, Any]:
    resolved_programs = list(programs) if programs is not None else matrix_programs(group)
    canonical_surface = _is_canonical_program_surface(group, resolved_programs)
    if protocol:
        run_protocol_suite(group if group in ("builder", "toolchain") else "all", runner=runner)
    results = [_audit_program(program, lab_root=lab_root) for program in resolved_programs]
    resolved_summary_path = summary_path or _default_audit_summary_path(
        group,
        resolved_programs,
        lab_root=lab_root,
    )
    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "group": group,
        "count": len(results),
        "protocol_checked": protocol,
        "canonical_surface": canonical_surface,
        "requested_programs": resolved_programs,
        "all_ok": all(result["ok"] for result in results),
        "results": results,
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def _family_name(program: str) -> str:
    return program[:-10] if program.endswith("_toolchain") else program


def _run_id_from_entry(entry: dict[str, Any] | None) -> str | None:
    if not entry:
        return None
    run_dir = entry.get("run_dir")
    if not run_dir:
        return None
    return Path(run_dir).name


def _result_map_by_family(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_family_name(result["program"]): result for result in results}


def _sorted_unique(values: list[str | None]) -> list[str]:
    return sorted({value for value in values if value})


def authority_required_families(*,
                                builder_programs: list[str] | None = None,
                                toolchain_programs: list[str] | None = None) -> list[str]:
    if builder_programs is None and toolchain_programs is None:
        authority = load_mainline_gate_authority()
        return _sorted_unique(list(authority.get("required_families", [])))

    authority_programs: list[str] = []
    if builder_programs is not None:
        authority_programs.extend(builder_programs)
    if toolchain_programs is not None:
        authority_programs.extend(toolchain_programs)
    if not authority_programs:
        authority_programs.extend(REFERENCE_REGRESSION_PROGRAMS)
    return _sorted_unique([_family_name(program) for program in authority_programs])


def _family_row_drifted(row: dict[str, Any]) -> bool:
    return row.get("audit", {}).get("manifest_match") is not True


def _family_row_failed(row: dict[str, Any]) -> bool:
    builder_ok = bool(row.get("builder", {}).get("run_dir"))
    toolchain_ok = bool(row.get("toolchain", {}).get("run_dir"))
    audit_ok = row.get("audit", {}).get("ok") is True
    return not (builder_ok and toolchain_ok and audit_ok)


def _family_day_failed(day: dict[str, Any]) -> bool:
    builder_ok = bool(day.get("builder_run_id"))
    toolchain_ok = bool(day.get("toolchain_run_id"))
    audit_ok = day.get("audit_ok") is True
    return not (builder_ok and toolchain_ok and audit_ok)


def _family_day_healthy(day: dict[str, Any]) -> bool:
    return not _family_day_failed(day) and day.get("manifest_match") is True


def _first_matching_date(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> str | None:
    for row in sorted(rows, key=lambda item: item["date"]):
        if predicate(row):
            return row["date"]
    return None


def _latest_recovered_date(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> str | None:
    unhealthy_seen = False
    recovered_date = None
    for row in sorted(rows, key=lambda item: item["date"]):
        if predicate(row):
            unhealthy_seen = True
            continue
        if unhealthy_seen:
            recovered_date = row["date"]
    return recovered_date


def _latest_recovery_start_date(rows: list[dict[str, Any]],
                                predicate: Callable[[dict[str, Any]], bool]) -> str | None:
    unhealthy_seen = False
    recovery_start = None
    for row in sorted(rows, key=lambda item: item["date"]):
        if predicate(row):
            unhealthy_seen = True
            recovery_start = None
            continue
        if unhealthy_seen and recovery_start is None:
            recovery_start = row["date"]
    return recovery_start


def build_nightly_index(builder_summary: dict[str, Any],
                        toolchain_summary: dict[str, Any],
                        toolchain_audit: dict[str, Any],
                        *,
                        requested_builder_programs: list[str] | None = None,
                        requested_toolchain_programs: list[str] | None = None,
                        canonical_surface: bool | None = None,
                        output_path: Path | None = None,
                        lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    builder_map = _result_map_by_family(builder_summary.get("results", []))
    toolchain_map = _result_map_by_family(toolchain_summary.get("results", []))
    audit_map = _result_map_by_family(toolchain_audit.get("results", []))
    families = sorted(set(builder_map) | set(toolchain_map) | set(audit_map))

    family_rows: list[dict[str, Any]] = []
    for family in families:
        builder_entry = builder_map.get(family)
        toolchain_entry = toolchain_map.get(family)
        audit_entry = audit_map.get(family)
        family_rows.append(
            {
                "family": family,
                "builder": {
                    "program": builder_entry.get("program") if builder_entry else None,
                    "run_dir": builder_entry.get("run_dir") if builder_entry else None,
                    "run_id": _run_id_from_entry(builder_entry),
                    "manifest_path": builder_entry.get("manifest_path") if builder_entry else None,
                },
                "toolchain": {
                    "program": toolchain_entry.get("program") if toolchain_entry else None,
                    "run_dir": toolchain_entry.get("run_dir") if toolchain_entry else None,
                    "run_id": _run_id_from_entry(toolchain_entry),
                    "manifest_path": toolchain_entry.get("manifest_path") if toolchain_entry else None,
                },
                "audit": {
                    "program": audit_entry.get("program") if audit_entry else None,
                    "latest_manifest": audit_entry.get("latest_manifest") if audit_entry else None,
                    "manifest_run_dir": audit_entry.get("manifest_run_dir") if audit_entry else None,
                    "manifest_match": audit_entry.get("manifest_match") if audit_entry else None,
                    "ok": audit_entry.get("ok") if audit_entry else None,
                },
            }
        )

    resolved_output_path = output_path or default_reference_path("nightly-index", lab_root=lab_root)
    resolved_builder_programs = (
        list(requested_builder_programs)
        if requested_builder_programs is not None
        else [result.get("program") for result in builder_summary.get("results", []) if result.get("program")]
    )
    resolved_toolchain_programs = (
        list(requested_toolchain_programs)
        if requested_toolchain_programs is not None
        else [result.get("program") for result in toolchain_summary.get("results", []) if result.get("program")]
    )
    resolved_canonical_surface = (
        bool(canonical_surface)
        if canonical_surface is not None
        else _is_canonical_nightly_surface(resolved_builder_programs, resolved_toolchain_programs)
    )
    index = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_DATED_NIGHTLY_INDEX,
            scope="builder_toolchain_audit_only",
            producer="riscv_snn_lab.build_nightly_index",
        ),
        "canonical_surface": resolved_canonical_surface,
        "count": len(family_rows),
        "requested_builder_programs": resolved_builder_programs,
        "requested_toolchain_programs": resolved_toolchain_programs,
        "builder_summary_path": builder_summary.get("summary_path"),
        "toolchain_summary_path": toolchain_summary.get("summary_path"),
        "toolchain_audit_summary_path": toolchain_audit.get("summary_path"),
        "all_ok": bool(toolchain_audit.get("all_ok")) and all(
            row["builder"]["run_dir"] and row["toolchain"]["run_dir"] for row in family_rows
        ),
        "families": family_rows,
    }
    _write_json(resolved_output_path, index)
    index["summary_path"] = str(resolved_output_path)
    return index


def _date_from_dated_reference(path: Path) -> str | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})-", path.name)
    return match.group(1) if match else None


def _generated_utc_timestamp(generated_utc: Any) -> float:
    if not generated_utc:
        return float("-inf")
    try:
        return dt.datetime.fromisoformat(str(generated_utc).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _path_mtime(path: Path | None) -> float:
    if path is None or not path.exists():
        return float("-inf")
    return path.stat().st_mtime


def _optional_surface_freshness_key(payload: dict[str, Any], *, summary_path: str | None = None) -> tuple[str, float, float]:
    resolved_summary_path = summary_path or payload.get("summary_path")
    path = Path(str(resolved_summary_path)) if resolved_summary_path else None
    return (
        (
            _date_from_dated_reference(path)
            if path is not None
            else None
        )
        or _date_from_generated_utc(payload.get("generated_utc"))
        or "",
        _generated_utc_timestamp(payload.get("generated_utc")),
        _path_mtime(path),
    )


def build_history_index(index_paths: list[Path],
                        *,
                        output_path: Path | None = None,
                        lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    nightly_rows: list[dict[str, Any]] = []
    family_history_map: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(index_paths):
        date_str = _date_from_dated_reference(path)
        if date_str is None:
            continue
        nightly = _load_json(path)
        drift_families = _sorted_unique(
            [row.get("family") for row in nightly.get("families", []) if _family_row_drifted(row)]
        )
        failed_families = _sorted_unique(
            [row.get("family") for row in nightly.get("families", []) if _family_row_failed(row)]
        )
        healthy = bool(nightly.get("all_ok")) and not drift_families and not failed_families
        nightly_rows.append(
            {
                "date": date_str,
                "summary_path": str(path),
                "count": nightly.get("count", 0),
                "all_ok": bool(nightly.get("all_ok")),
                "builder_summary_path": nightly.get("builder_summary_path"),
                "toolchain_summary_path": nightly.get("toolchain_summary_path"),
                "toolchain_audit_summary_path": nightly.get("toolchain_audit_summary_path"),
                "drift_families": drift_families,
                "failed_families": failed_families,
                "healthy": healthy,
            }
        )
        for row in nightly.get("families", []):
            day = {
                "date": date_str,
                "summary_path": str(path),
                "builder_run_id": row.get("builder", {}).get("run_id"),
                "toolchain_run_id": row.get("toolchain", {}).get("run_id"),
                "manifest_match": row.get("audit", {}).get("manifest_match"),
                "audit_ok": row.get("audit", {}).get("ok"),
            }
            day["healthy"] = _family_day_healthy(day)
            family_history_map.setdefault(row["family"], []).append(day)

    nightly_rows.sort(key=lambda row: row["date"], reverse=True)
    family_history = [
        {
            "family": family,
            "days": sorted(days, key=lambda row: row["date"], reverse=True),
            "first_fail_date": _first_matching_date(days, _family_day_failed),
            "first_drift_date": _first_matching_date(days, lambda row: row.get("manifest_match") is not True),
            "latest_recovered_date": _latest_recovered_date(
                days,
                lambda row: _family_day_failed(row) or row.get("manifest_match") is not True,
            ),
        }
        for family, days in sorted(family_history_map.items())
    ]

    resolved_output_path = output_path or stable_reference_path("nightly-history-index", lab_root=lab_root)
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_HISTORY_ROLLUP,
            scope="historical_rollup_only",
            producer="riscv_snn_lab.build_history_index",
        ),
        "count": len(nightly_rows),
        "latest_date": nightly_rows[0]["date"] if nightly_rows else None,
        "latest_summary_path": nightly_rows[0]["summary_path"] if nightly_rows else None,
        "all_ok_latest": bool(nightly_rows[0]["all_ok"]) if nightly_rows else False,
        "all_ok_all": all(row["all_ok"] for row in nightly_rows) if nightly_rows else False,
        "first_fail_date": _first_matching_date(
            nightly_rows,
            lambda row: (not row["healthy"]) and bool(row["failed_families"]),
        ),
        "first_drift_date": _first_matching_date(
            nightly_rows,
            lambda row: bool(row["drift_families"]),
        ),
        "latest_recovered_date": _latest_recovered_date(
            nightly_rows,
            lambda row: (not row["healthy"]),
        ),
        "entries": nightly_rows,
        "family_history": family_history,
    }
    _write_json(resolved_output_path, history)
    history["summary_path"] = str(resolved_output_path)
    return history


def refresh_history_index(*,
                          lab_root: Path = LAB_ROOT,
                          output_path: Path | None = None) -> dict[str, Any]:
    index_paths = sorted((lab_root / "references").glob("*-nightly-index.json"))
    return build_history_index(index_paths, output_path=output_path, lab_root=lab_root)


def _date_from_generated_utc(generated_utc: Any) -> str | None:
    if not generated_utc:
        return None
    try:
        return dt.datetime.fromisoformat(str(generated_utc).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _parsed_generated_utc(generated_utc: Any) -> dt.datetime | None:
    if not generated_utc:
        return None
    try:
        return dt.datetime.fromisoformat(str(generated_utc).replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_surface_preference_key(generated_utc: Any, *, source_kind: str) -> tuple[dt.datetime, int]:
    return (
        _parsed_generated_utc(generated_utc) or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        1 if source_kind == "group_matrix" else 0,
    )


def _optional_surface_candidate_key(payload: dict[str, Any],
                                    *,
                                    summary_path: Path | None,
                                    source_kind: str) -> tuple[str, dt.datetime, int]:
    return (
        _date_from_dated_reference(summary_path or Path(payload.get("summary_path", "")))
        or _date_from_generated_utc(payload.get("generated_utc"))
        or "",
        _parsed_generated_utc(payload.get("generated_utc")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        1 if source_kind == "group_matrix" else 0,
    )


def _full_equivalence_history_entry(payload: dict[str, Any], *, summary_path: str | None = None) -> dict[str, Any]:
    family_names = _sorted_unique([row.get("family") for row in payload.get("families", [])])
    return {
        "date": (
            _date_from_dated_reference(Path(summary_path or payload.get("summary_path", "")))
            or _date_from_generated_utc(payload.get("generated_utc"))
            or dt.date.today().isoformat()
        ),
        "summary_path": summary_path or payload.get("summary_path"),
        "generated_utc": payload.get("generated_utc"),
        "source_kind": "group_matrix",
        "canonical_surface": bool(payload.get("canonical_surface")),
        "requested_group": payload.get("requested_group"),
        "count": payload.get("count", len(family_names)),
        "all_ok": bool(payload.get("all_ok")),
        "family_names": family_names,
    }


def _optional_single_family_history_entry(payload: dict[str, Any],
                                          *,
                                          group: str,
                                          family: str,
                                          summary_path: str | None = None) -> dict[str, Any]:
    return {
        "date": (
            _date_from_dated_reference(Path(summary_path or payload.get("summary_path", "")))
            or _date_from_generated_utc(payload.get("generated_utc"))
            or dt.date.today().isoformat()
        ),
        "summary_path": summary_path or payload.get("summary_path"),
        "generated_utc": payload.get("generated_utc"),
        "source_kind": "singleton_family_equivalence",
        "canonical_surface": True,
        "requested_group": group,
        "count": 1,
        "all_ok": str(payload.get("status", "")).upper() == "PASS",
        "family_names": [family],
    }


def _optional_single_family_equivalence_payload(payload: dict[str, Any],
                                                *,
                                                group: str,
                                                family: str,
                                                summary_path: str | None = None) -> dict[str, Any]:
    row = _optional_single_family_history_entry(
        payload,
        group=group,
        family=family,
        summary_path=summary_path,
    )
    return {
        "artifact_role": payload.get("artifact_role") or "dated_equivalence_family_surface",
        "canonical_surface": row["canonical_surface"],
        "requested_group": row["requested_group"],
        "count": row["count"],
        "all_ok": row["all_ok"],
        "families": [
            {
                "family": family,
                "status": payload.get("status"),
                "gate_reasons": list(payload.get("gate_reasons", []) or []),
                "summary_path": row["summary_path"],
            }
        ],
        "summary_path": row["summary_path"],
        "generated_utc": payload.get("generated_utc"),
        "source_family": family,
        "source_kind": "singleton_family_equivalence",
    }


def _prefer_optional_history_row(existing: dict[str, Any] | None,
                                 candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    existing_key = _optional_surface_preference_key(
        existing.get("generated_utc"),
        source_kind=str(existing.get("source_kind") or ""),
    )
    candidate_key = _optional_surface_preference_key(
        candidate.get("generated_utc"),
        source_kind=str(candidate.get("source_kind") or ""),
    )
    if candidate_key > existing_key:
        return candidate
    return existing


def _optional_history_row_from_payload(payload: dict[str, Any],
                                       *,
                                       group: str,
                                       summary_path: Path | None = None,
                                       lab_root: Path = LAB_ROOT) -> tuple[dict[str, Any] | None, str | None]:
    resolved_summary_path = summary_path or (
        Path(str(payload.get("summary_path"))) if payload.get("summary_path") else None
    )
    reason = _optional_equivalence_history_exclusion_reason(payload, group=group)
    if reason is None:
        return _full_equivalence_history_entry(
            payload,
            summary_path=str(resolved_summary_path) if resolved_summary_path is not None else None,
        ), None

    singleton_family = _optional_group_singleton_family(group, lab_root=lab_root)
    payload_family = str(payload.get("family") or "")
    if singleton_family is not None and payload_family == singleton_family:
        return _optional_single_family_history_entry(
            payload,
            group=group,
            family=singleton_family,
            summary_path=str(resolved_summary_path) if resolved_summary_path is not None else None,
        ), None
    return None, reason


def _optional_history_freshness_rollup(group_history: dict[str, Any],
                                       *,
                                       mode: str = "all_dates") -> dict[str, Any]:
    entries = list(group_history.get("entries", []) or [])
    latest_recovered_date = group_history.get("latest_recovered_date")
    effective_entries = entries
    if mode == "since_latest_recovery" and latest_recovered_date:
        effective_entries = [
            row for row in entries if str(row.get("date") or "") >= str(latest_recovered_date)
        ]
    effective_entry_count = len(effective_entries)
    effective_all_dates_ok = (
        all(bool(row.get("all_ok")) for row in effective_entries)
        if effective_entries
        else bool(group_history.get("all_dates_ok"))
    )
    return {
        "mode": mode,
        "raw_entry_count": int(group_history.get("entry_count", 0)),
        "raw_all_dates_ok": bool(group_history.get("all_dates_ok")),
        "latest_recovered_date": latest_recovered_date,
        "effective_entry_count": effective_entry_count,
        "effective_all_dates_ok": effective_all_dates_ok,
    }


def _artifact_isolation_history_entry(report: dict[str, Any]) -> dict[str, Any]:
    surfaces = dict(report.get("surfaces", {}) or {})
    regressed_surfaces = sorted(
        name for name, row in surfaces.items() if not bool(row.get("canonical_unchanged"))
    )
    subset_surface_map = {
        name: row.get("subset_surface")
        for name, row in sorted(surfaces.items())
    }
    return {
        "date": _date_from_generated_utc(report.get("generated_utc")) or dt.date.today().isoformat(),
        "summary_path": report.get("summary_path"),
        "all_ok": bool(report.get("all_ok")),
        "surface_count": len(surfaces),
        "regressed_surfaces": regressed_surfaces,
        "subset_surfaces": subset_surface_map,
    }


def _full_equivalence_history_exclusion_reason(payload: dict[str, Any]) -> str | None:
    if payload.get("artifact_role") != ARTIFACT_ROLE_DATED_EQUIV_MATRIX:
        return "unexpected_artifact_role"
    if str(payload.get("requested_group")) != "all":
        return "non_full_all_group"
    if not bool(payload.get("canonical_surface")):
        return "non_canonical_surface"
    return None


def _optional_equivalence_history_exclusion_reason(payload: dict[str, Any], *, group: str) -> str | None:
    if payload.get("artifact_role") != ARTIFACT_ROLE_DATED_EQUIV_MATRIX:
        return "unexpected_artifact_role"
    if str(payload.get("requested_group")) != group:
        return f"non_{group}_group"
    if not bool(payload.get("canonical_surface")):
        return "non_canonical_surface"
    return None


def refresh_full_equivalence_history(*,
                                     full_equivalence: dict[str, Any] | None = None,
                                     lab_root: Path = LAB_ROOT,
                                     output_path: Path | None = None) -> dict[str, Any]:
    entries_by_date: dict[str, dict[str, Any]] = {}
    excluded_by_date: dict[str, dict[str, Any]] = {}
    for path in sorted((lab_root / "references").glob("*-equiv-matrix.json")):
        date_str = _date_from_dated_reference(path)
        if date_str is None:
            continue
        payload = _load_json(path)
        row = _full_equivalence_history_entry(payload, summary_path=str(path))
        reason = _full_equivalence_history_exclusion_reason(payload)
        if reason is not None:
            if row["date"] not in entries_by_date:
                excluded_by_date[row["date"]] = {
                    **row,
                    "reason": reason,
                }
            continue
        entries_by_date[row["date"]] = row
        excluded_by_date.pop(row["date"], None)

    if full_equivalence:
        row = _full_equivalence_history_entry(full_equivalence)
        reason = _full_equivalence_history_exclusion_reason(full_equivalence)
        if reason is None:
            entries_by_date[row["date"]] = row
            excluded_by_date.pop(row["date"], None)
        elif row["date"] not in entries_by_date:
            excluded_by_date[row["date"]] = {
                **row,
                "reason": reason,
            }

    entries_asc = sorted(entries_by_date.values(), key=lambda row: row["date"])
    previous_family_names: list[str] = []
    for idx, row in enumerate(entries_asc):
        current_family_names = list(row.get("family_names", []))
        if idx == 0:
            row["added_families_vs_previous"] = []
            row["removed_families_vs_previous"] = []
        else:
            row["added_families_vs_previous"] = [name for name in current_family_names if name not in previous_family_names]
            row["removed_families_vs_previous"] = [name for name in previous_family_names if name not in current_family_names]
        previous_family_names = current_family_names

    entries_desc = list(reversed(entries_asc))
    excluded_entries = sorted(excluded_by_date.values(), key=lambda row: row["date"], reverse=True)
    resolved_output_path = output_path or stable_reference_path("full-equivalence-history", lab_root=lab_root)
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_FULL_EQUIVALENCE_HISTORY,
            scope="research_surface_rollup_only",
            producer="riscv_snn_lab.refresh_full_equivalence_history",
        ),
        "history_contract": "canonical_full_all_only",
        "entry_count": len(entries_desc),
        "excluded_entry_count": len(excluded_entries),
        "latest_date": entries_desc[0]["date"] if entries_desc else None,
        "latest_summary_path": entries_desc[0]["summary_path"] if entries_desc else None,
        "all_ok_latest": bool(entries_desc[0]["all_ok"]) if entries_desc else False,
        "all_dates_ok": all(bool(row.get("all_ok")) for row in entries_desc) if entries_desc else False,
        "first_fail_date": _first_matching_date(entries_desc, lambda row: not bool(row.get("all_ok"))),
        "latest_recovered_date": _latest_recovered_date(entries_desc, lambda row: not bool(row.get("all_ok"))),
        "entries": entries_desc,
        "excluded_entries": excluded_entries,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, history)
    return history


def refresh_optional_equivalence_history(*,
                                         group: str = "queue_optional",
                                         optional_equivalence: dict[str, Any] | None = None,
                                         sample_paths: list[Path] | None = None,
                                         compact_since_latest_recovery: bool = False,
                                         reset_existing: bool = False,
                                         lab_root: Path = LAB_ROOT,
                                         output_path: Path | None = None) -> dict[str, Any]:
    resolved_output_path = output_path or stable_reference_path(
        f"{group.replace('_', '-')}-equivalence-history",
        lab_root=lab_root,
    )
    entries_by_date: dict[str, dict[str, Any]] = {}
    excluded_by_date: dict[str, dict[str, Any]] = {}
    if sample_paths is not None:
        if not reset_existing and resolved_output_path.exists():
            existing = _load_json(resolved_output_path)
            for row in existing.get("entries", []):
                if isinstance(row, dict) and row.get("date"):
                    entries_by_date[str(row["date"])] = dict(row)
            for row in existing.get("excluded_entries", []):
                if isinstance(row, dict) and row.get("date"):
                    excluded_by_date[str(row["date"])] = dict(row)

        for path in sample_paths:
            payload = _load_json(path)
            row, reason = _optional_history_row_from_payload(
                payload,
                group=group,
                summary_path=path,
                lab_root=lab_root,
            )
            if row is None:
                date_key = (
                    _date_from_dated_reference(path)
                    or _date_from_generated_utc(payload.get("generated_utc"))
                    or dt.date.today().isoformat()
                )
                if date_key not in entries_by_date:
                    excluded_by_date[date_key] = {
                        "date": date_key,
                        "summary_path": str(path),
                        "reason": reason or "invalid_optional_history_sample",
                    }
                continue
            entries_by_date[row["date"]] = _prefer_optional_history_row(entries_by_date.get(row["date"]), row)
            excluded_by_date.pop(row["date"], None)
    else:
        for path in sorted((lab_root / "references").glob(_optional_group_matrix_pattern(group))):
            date_str = _date_from_dated_reference(path)
            if date_str is None:
                continue
            payload = _load_json(path)
            row, reason = _optional_history_row_from_payload(
                payload,
                group=group,
                summary_path=path,
                lab_root=lab_root,
            )
            if row is None:
                if date_str not in entries_by_date:
                    excluded_by_date[date_str] = {
                        "date": date_str,
                        "summary_path": str(path),
                        "reason": reason or "invalid_optional_history_sample",
                    }
                continue
            entries_by_date[row["date"]] = _prefer_optional_history_row(entries_by_date.get(row["date"]), row)
            excluded_by_date.pop(row["date"], None)

        singleton_family = _optional_group_singleton_family(group, lab_root=lab_root)
        if singleton_family is not None:
            for path in sorted((lab_root / "references").glob(_optional_group_family_equiv_pattern(singleton_family))):
                date_str = _date_from_dated_reference(path)
                if date_str is None:
                    continue
                payload = _load_json(path)
                row, reason = _optional_history_row_from_payload(
                    payload,
                    group=group,
                    summary_path=path,
                    lab_root=lab_root,
                )
                if row is None:
                    if date_str not in entries_by_date:
                        excluded_by_date[date_str] = {
                            "date": date_str,
                            "summary_path": str(path),
                            "reason": reason or "invalid_optional_history_sample",
                        }
                    continue
                entries_by_date[row["date"]] = _prefer_optional_history_row(entries_by_date.get(row["date"]), row)
                excluded_by_date.pop(row["date"], None)

    if optional_equivalence:
        row, reason = _optional_history_row_from_payload(
            optional_equivalence,
            group=group,
            lab_root=lab_root,
        )
        if row is not None:
            entries_by_date[row["date"]] = _prefer_optional_history_row(entries_by_date.get(row["date"]), row)
            excluded_by_date.pop(row["date"], None)
        else:
            date_key = (
                _date_from_generated_utc(optional_equivalence.get("generated_utc"))
                or dt.date.today().isoformat()
            )
            if date_key not in entries_by_date:
                excluded_by_date[date_key] = {
                    "date": date_key,
                    "summary_path": optional_equivalence.get("summary_path"),
                    "reason": reason or "invalid_optional_history_sample",
                }

    compacted_entries: list[dict[str, Any]] = []
    refresh_mode = "compact_samples" if sample_paths is not None else "dated_scan"
    if compact_since_latest_recovery:
        latest_recovered_date = _latest_recovery_start_date(
            list(entries_by_date.values()),
            lambda row: not bool(row.get("all_ok")),
        )
        if latest_recovered_date:
            for date_key, row in list(entries_by_date.items()):
                if str(row.get("date") or "") < str(latest_recovered_date):
                    compacted_entries.append(
                        {
                            **row,
                            "reason": "compacted_before_latest_recovery",
                        }
                    )
                    del entries_by_date[date_key]
        refresh_mode = "compact_latest_recovery"

    entries_desc = sorted(entries_by_date.values(), key=lambda row: row["date"], reverse=True)
    excluded_entries = sorted(
        [*excluded_by_date.values(), *compacted_entries],
        key=lambda row: row["date"],
        reverse=True,
    )
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_OPTIONAL_EQUIVALENCE_HISTORY,
            scope="research_surface_rollup_only",
            producer="riscv_snn_lab.refresh_optional_equivalence_history",
        ),
        "group": group,
        "history_contract": f"canonical_{group}_only",
        "refresh_mode": refresh_mode,
        "reset_existing": bool(reset_existing) if sample_paths is not None else False,
        "entry_count": len(entries_desc),
        "excluded_entry_count": len(excluded_entries),
        "latest_date": entries_desc[0]["date"] if entries_desc else None,
        "latest_summary_path": entries_desc[0]["summary_path"] if entries_desc else None,
        "all_ok_latest": bool(entries_desc[0]["all_ok"]) if entries_desc else False,
        "all_dates_ok": all(bool(row.get("all_ok")) for row in entries_desc) if entries_desc else False,
        "first_fail_date": _first_matching_date(entries_desc, lambda row: not bool(row.get("all_ok"))),
        "latest_recovered_date": _latest_recovery_start_date(
            entries_desc,
            lambda row: not bool(row.get("all_ok")),
        ),
        "entries": entries_desc,
        "excluded_entries": excluded_entries,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, history)
    return history


def _observer_full_equivalence_history_entry(payload: dict[str, Any]) -> dict[str, Any]:
    row = _full_equivalence_history_entry(payload)
    sample_generated_utc = payload.get("generated_utc")
    sample_key = str(sample_generated_utc or row["summary_path"] or row["date"])
    return {
        **row,
        "sample_generated_utc": sample_generated_utc,
        "sample_key": sample_key,
    }


def refresh_observer_full_equivalence_history(*,
                                              full_equivalence: dict[str, Any] | None = None,
                                              compact_since_latest_recovery: bool = False,
                                              lab_root: Path = LAB_ROOT,
                                              output_path: Path | None = None) -> dict[str, Any]:
    resolved_output_path = output_path or stable_reference_path(
        "observer-full-equivalence-history",
        lab_root=lab_root,
    )
    entries_by_key: dict[str, dict[str, Any]] = {}
    if resolved_output_path.exists():
        existing = _load_json(resolved_output_path)
        for row in existing.get("entries", []):
            if isinstance(row, dict) and row.get("sample_key"):
                entries_by_key[str(row["sample_key"])] = dict(row)

    excluded_entries: list[dict[str, Any]] = []
    if full_equivalence:
        row = _observer_full_equivalence_history_entry(full_equivalence)
        reason = _full_equivalence_history_exclusion_reason(full_equivalence)
        if reason is None:
            entries_by_key[row["sample_key"]] = row
        else:
            excluded_entries.append({**row, "reason": reason})

    entries_desc = sorted(
        entries_by_key.values(),
        key=lambda row: (
            row.get("sample_generated_utc") or "",
            row.get("summary_path") or "",
            row["date"],
        ),
        reverse=True,
    )
    entries_asc = list(reversed(entries_desc))
    unhealthy_seen = False
    latest_recovered_date = None
    for row in entries_asc:
        if not bool(row.get("all_ok")):
            unhealthy_seen = True
            continue
        if unhealthy_seen:
            latest_recovered_date = row["date"]
    effective_entries_desc = list(entries_desc)
    compacted_entries: list[dict[str, Any]] = []
    refresh_mode = "sample_sequence"
    if compact_since_latest_recovery:
        refresh_mode = "compact_latest_recovery"
        if latest_recovered_date:
            effective_entries_desc = [
                row for row in entries_desc
                if row["date"] >= latest_recovered_date
            ]
            compacted_entries = [
                {**row, "reason": "compacted_before_latest_recovery"}
                for row in entries_desc
                if row["date"] < latest_recovered_date
            ]
    effective_entry_count = len(effective_entries_desc)
    effective_all_dates_ok = (
        all(bool(row.get("all_ok")) for row in effective_entries_desc)
        if effective_entries_desc
        else False
    )
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_OBSERVER_FULL_EQUIVALENCE_HISTORY,
            scope="research_surface_rollup_only",
            producer="riscv_snn_lab.refresh_observer_full_equivalence_history",
        ),
        "history_contract": "observer_sample_sequence_v1",
        "refresh_mode": refresh_mode,
        "entry_count": len(entries_desc),
        "effective_entry_count": effective_entry_count,
        "effective_all_dates_ok": effective_all_dates_ok,
        "excluded_entry_count": len(excluded_entries),
        "compacted_entry_count": len(compacted_entries),
        "latest_date": entries_desc[0]["date"] if entries_desc else None,
        "latest_summary_path": entries_desc[0]["summary_path"] if entries_desc else None,
        "all_ok_latest": bool(entries_desc[0]["all_ok"]) if entries_desc else False,
        "all_dates_ok": all(bool(row.get("all_ok")) for row in entries_desc) if entries_desc else False,
        "first_fail_date": _first_matching_date(entries_asc, lambda row: not bool(row.get("all_ok"))),
        "latest_recovered_date": latest_recovered_date,
        "entries": entries_desc,
        "excluded_entries": excluded_entries,
        "compacted_entries": compacted_entries,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, history)
    return history


def refresh_observer_history_surface(*,
                                     sample_paths: list[Path] | None = None,
                                     compact_since_latest_recovery: bool = False,
                                     output_path: Path | None = None,
                                     lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    history = None
    resolved_sample_paths = list(sample_paths or [])
    for sample_path in resolved_sample_paths:
        history = refresh_observer_full_equivalence_history(
            full_equivalence=_load_json(sample_path),
            compact_since_latest_recovery=compact_since_latest_recovery,
            lab_root=lab_root,
            output_path=output_path,
        )
    if history is None:
        history = refresh_observer_full_equivalence_history(
            compact_since_latest_recovery=compact_since_latest_recovery,
            lab_root=lab_root,
            output_path=output_path,
        )
    return history


def refresh_artifact_isolation_history(report: dict[str, Any],
                                       *,
                                       lab_root: Path = LAB_ROOT,
                                       output_path: Path | None = None) -> dict[str, Any]:
    resolved_output_path = output_path or stable_reference_path("artifact-isolation-history", lab_root=lab_root)
    entries_by_date: dict[str, dict[str, Any]] = {}
    if resolved_output_path.exists():
        existing = _load_json(resolved_output_path)
        for row in existing.get("entries", []):
            if isinstance(row, dict) and row.get("date"):
                entries_by_date[str(row["date"])] = dict(row)

    latest_entry = _artifact_isolation_history_entry(report)
    entries_by_date[latest_entry["date"]] = latest_entry
    entries_desc = sorted(entries_by_date.values(), key=lambda row: row["date"], reverse=True)
    history = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_ARTIFACT_ISOLATION_HISTORY,
            scope="research_surface_rollup_only",
            producer="riscv_snn_lab.refresh_artifact_isolation_history",
        ),
        "entry_count": len(entries_desc),
        "latest_date": entries_desc[0]["date"] if entries_desc else None,
        "latest_summary_path": entries_desc[0]["summary_path"] if entries_desc else None,
        "all_ok_latest": bool(entries_desc[0]["all_ok"]) if entries_desc else False,
        "all_dates_ok": all(bool(row.get("all_ok")) for row in entries_desc) if entries_desc else False,
        "first_fail_date": _first_matching_date(entries_desc, lambda row: not bool(row.get("all_ok"))),
        "latest_recovered_date": _latest_recovered_date(entries_desc, lambda row: not bool(row.get("all_ok"))),
        "entries": entries_desc,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, history)
    return history


def evaluate_nightly_gate(nightly_index: dict[str, Any],
                          *,
                          required_families: list[str] | None = None,
                          min_count: int | None = None) -> dict[str, Any]:
    resolved_required_families = _sorted_unique(
        list(required_families) if required_families is not None else authority_required_families()
    )
    resolved_min_count = int(min_count) if min_count is not None else len(resolved_required_families)
    actual_families = _sorted_unique([row.get("family") for row in nightly_index.get("families", [])])
    missing_families = [family for family in resolved_required_families if family not in actual_families]
    unexpected_families = [family for family in actual_families if family not in resolved_required_families]
    drift_families = _sorted_unique(
        [row.get("family") for row in nightly_index.get("families", []) if _family_row_drifted(row)]
    )
    failed_families = _sorted_unique(
        [row.get("family") for row in nightly_index.get("families", []) if _family_row_failed(row)]
    )
    reasons: list[str] = []
    if int(nightly_index.get("count", 0)) < resolved_min_count:
        reasons.append(f"nightly family count {nightly_index.get('count', 0)} < required {resolved_min_count}")
    if missing_families:
        reasons.append(f"missing required families: {', '.join(missing_families)}")
    if not bool(nightly_index.get("all_ok")):
        reasons.append("nightly index all_ok is false")
    for family in drift_families:
        reasons.append(f"{family} manifest drift detected")
    return {
        "gate_name": SIDECAR_GATE_NAME,
        "gate_version": SIDECAR_GATE_VERSION,
        "gate_ok": not reasons,
        "reasons": reasons,
        "required_families": resolved_required_families,
        "missing_families": missing_families,
        "unexpected_families": unexpected_families,
        "failed_families": failed_families,
        "drift_families": drift_families,
        "min_count": resolved_min_count,
        "actual_count": int(nightly_index.get("count", 0)),
    }


def build_sidecar_summary_md(report: dict[str, Any],
                             *,
                             output_path: Path | None = None,
                             lab_root: Path = LAB_ROOT) -> Path:
    resolved_output_path = output_path or stable_markdown_path("nightly-sidecar-summary", lab_root=lab_root)
    nightly_index = report.get("nightly_index", {})
    history_index = report.get("history_index", {})
    optional_group_surfaces = _report_optional_group_surfaces(report)
    equivalence = report.get("equivalence")
    full_equivalence = report.get("full_equivalence")
    full_equivalence_history = report.get("full_equivalence_history")
    queue_equivalence = optional_group_surfaces.get("queue_optional")
    nonqueue_optional_group_surfaces = {
        group: dict(payload or {})
        for group, payload in sorted(optional_group_surfaces.items())
        if group != "queue_optional"
    }
    artifact_isolation = report.get("artifact_isolation")
    artifact_isolation_history = report.get("artifact_isolation_history")
    abi_audit = report.get("abi_audit")
    timing = report.get("timing", {})
    reasons = report.get("reasons", [])
    family_rows = nightly_index.get("families", [])
    status = "PASS" if report.get("gate_ok") else "FAIL"
    required_families = report.get("required_families", [])
    missing_families = report.get("missing_families", [])
    stable_surface_refresh = dict(report.get("stable_surface_refresh") or {})
    supplementary_surfaces = _report_supplementary_surfaces(report, lab_root=lab_root)
    compare_surface = dict(supplementary_surfaces.get("compare") or {})
    compare_rollup = (
        _supplementary_surface_rollup("compare", compare_surface, lab_root=lab_root)
        if compare_surface
        else {}
    )
    reference_compare_surface = dict(supplementary_surfaces.get("reference_compare") or {})
    reference_compare_rollup = (
        _supplementary_surface_rollup("reference_compare", reference_compare_surface, lab_root=lab_root)
        if reference_compare_surface
        else {}
    )
    reference_program_compare_surface = dict(
        supplementary_surfaces.get("reference_program_compare") or {}
    )
    reference_program_compare_rollup = (
        _supplementary_surface_rollup(
            "reference_program_compare",
            reference_program_compare_surface,
            lab_root=lab_root,
        )
        if reference_program_compare_surface
        else {}
    )
    stat_snapshot_family_surface = dict(supplementary_surfaces.get("stat_snapshot_family") or {})
    stat_snapshot_family_rollup = (
        _supplementary_surface_rollup(
            "stat_snapshot_family",
            stat_snapshot_family_surface,
            lab_root=lab_root,
        )
        if stat_snapshot_family_surface
        else {}
    )
    supplementary_surface_history_path = (
        report.get("supplementary_surface_history_path")
        or stable_reference_path("supplementary-surface-history", lab_root=lab_root)
    )
    stable_surface_refresh_audit_path = (
        report.get("stable_surface_refresh_audit_path")
        or stable_reference_path("stable-surface-refresh-audit", lab_root=lab_root)
    )
    supplementary_surface_authority_path = _resolve_authority_path(
        lab_root=lab_root,
        default_path=SUPPLEMENTARY_SURFACE_AUTHORITY_PATH,
    )
    surface_generated_utc = (
        stable_surface_refresh.get("refreshed_utc")
        or report.get("generated_utc")
    )

    def _status_counts_text(payload: dict[str, Any] | None) -> str:
        counts = dict((payload or {}).get("status_counts") or {})
        if not counts:
            return "none"
        return ", ".join(f"{name}:{counts[name]}" for name in sorted(counts))

    def _append_preflight_rollup_lines(lines: list[str], payload: dict[str, Any] | None) -> None:
        rollup = dict(payload or {})
        if not rollup:
            return
        lines.extend([
            (
                "- Runtime-bridge build preflight (research-only): "
                f"`enabled={rollup.get('enabled')}` "
                f"`all_ok={rollup.get('all_ok')}` "
                f"`family_count={rollup.get('family_count')}` "
                f"`status_counts={_status_counts_text(rollup)}` "
                f"`contract_keys={','.join(rollup.get('contract_keys', [])) or 'none'}`"
            ),
        ])

    def _append_equivalence_rows(lines: list[str], payload: dict[str, Any]) -> None:
        lines.extend([
            "",
            "| family | status | preflight_status | gate_reasons |",
            "| --- | --- | --- | --- |",
        ])
        for row in payload.get("families", []):
            lines.append(
                "| {family} | {status} | {preflight_status} | {gate_reasons} |".format(
                    family=row.get("family", "unknown"),
                    status=row.get("status", "unknown"),
                    preflight_status=row.get("runtime_bridge_build_preflight_rollup", {}).get("status", "none"),
                    gate_reasons=", ".join(row.get("gate_reasons", [])) or "none",
                )
            )

    def _append_equivalence_block(lines: list[str],
                                  payload: dict[str, Any],
                                  *,
                                  group_label: str | None = None,
                                  history: dict[str, Any] | None = None) -> None:
        if group_label is not None:
            lines.append(f"- Group: `{group_label}`")
        lines.extend([
            f"- Surface: `{_surface_label(payload.get('canonical_surface'))}`",
            f"- Requested group: `{payload.get('requested_group')}`",
            f"- Gate name: `{payload.get('gate_name')}`",
            f"- All OK: `{payload.get('all_ok')}`",
            f"- Family count: `{payload.get('count', 0)}`",
            f"- Summary path: `{payload.get('summary_path')}`",
        ])
        if history is not None:
            lines.extend([
                f"- History path: `{history.get('summary_path') if history else 'none'}`",
                f"- History latest date: `{history.get('latest_date') if history else 'none'}`",
                f"- History entry count: `{history.get('entry_count') if history else 0}`",
            ])
        _append_preflight_rollup_lines(lines, payload.get("runtime_bridge_build_preflight_rollup"))
        _append_equivalence_rows(lines, payload)

    lines = [
        "# riscv_snn experimental nightly sidecar",
        "",
        f"- Generated UTC: `{surface_generated_utc}`",
        f"- Gate: {status}",
        f"- Gate name: `{report.get('gate_name')}`",
        f"- Gate version: `{report.get('gate_version')}`",
        f"- Artifact role: `{report.get('artifact_role')}`",
        f"- Authority scope: `{report.get('authority_scope')}`",
        f"- Latest nightly date: `{history_index.get('latest_date')}`",
        f"- Required families ({len(required_families)}): `{', '.join(required_families) if required_families else 'none'}`",
        f"- Missing families: `{', '.join(missing_families) if missing_families else 'none'}`",
        f"- First fail date: `{history_index.get('first_fail_date') or 'none'}`",
        f"- First drift date: `{history_index.get('first_drift_date') or 'none'}`",
        f"- Latest recovered date: `{history_index.get('latest_recovered_date') or 'none'}`",
        "",
        "## Authority",
        "",
        f"- stable top-level gate: `{report.get('report_path')}`",
        f"- stable observer summary: `{report.get('observer_summary_path') or 'none'}`",
        f"- shared current-state rollup: `{report.get('current_mainline_status_path') or 'none'}`",
        f"- current_mainline_status_path: `{report.get('current_mainline_status_path') or 'none'}`",
        f"- stable surface refresh UTC: `{stable_surface_refresh.get('refreshed_utc') or 'none'}`",
        f"- stable surface refresh observer summary: `{stable_surface_refresh.get('observer_summary_path') or 'none'}`",
        f"- stable surface refresh current mainline: `{stable_surface_refresh.get('current_mainline_status_path') or 'none'}`",
        f"- stable supplementary surface history: `{supplementary_surface_history_path or 'none'}`",
        f"- supplementary surface authority: `{supplementary_surface_authority_path}`",
        f"- stable surface refresh audit: `{stable_surface_refresh_audit_path or 'none'}`",
        f"- stable optional promotion dossier: `{(report.get('stable_surface_refresh') or {}).get('optional_promotion_dossier_path') or 'none'}`",
        f"- dated family-level equivalence authority: `{equivalence.get('summary_path') if equivalence else 'none'}`",
        f"- dated family-level equivalence authority surface: `{_surface_label(equivalence.get('canonical_surface')) if equivalence else 'none'}`",
        (
            "- dated full-all equivalence snapshot (research-only, non-blocking): "
            f"`{full_equivalence.get('summary_path') if full_equivalence else 'none'}`"
        ),
        (
            "- dated full-all equivalence snapshot surface: "
            f"`{_surface_label(full_equivalence.get('canonical_surface')) if full_equivalence else 'none'}`"
        ),
        (
            "- dated queue-optional equivalence matrix (research-only, non-blocking): "
            f"`{queue_equivalence.get('summary_path') if queue_equivalence else 'none'}`"
        ),
        (
            "- dated queue-optional equivalence surface: "
            f"`{_surface_label(queue_equivalence.get('canonical_surface')) if queue_equivalence else 'none'}`"
        ),
        f"- dated nightly index: `{nightly_index.get('summary_path')}`",
        f"- dated nightly index surface: `{_surface_label(nightly_index.get('canonical_surface'))}`",
        "- dated nightly index is not the equivalence authority",
        "",
        "## Reasons",
        "",
    ]
    authority_optional_group_lines: list[str] = []
    for group, payload in nonqueue_optional_group_surfaces.items():
        authority_optional_group_lines.extend([
            (
                f"- dated optional-group equivalence `{group}` (research-only, non-blocking): "
                f"`{payload.get('summary_path') or 'none'}`"
            ),
            (
                f"- dated optional-group equivalence surface `{group}`: "
                f"`{_surface_label(payload.get('canonical_surface'))}`"
            ),
        ])
    if compare_surface:
        authority_optional_group_lines.extend([
            (
                "- supplementary compare smoke gate (research-only, non-blocking): "
                f"`{compare_surface.get('report_path') or 'none'}`"
            ),
            (
                "- supplementary compare current-state rollup: "
                f"`{compare_surface.get('current_mainline_status_path') or 'none'}`"
            ),
        ])
    if reference_compare_surface:
        authority_optional_group_lines.extend([
            (
                "- supplementary reference compare gate (research-only, non-blocking): "
                f"`{reference_compare_surface.get('report_path') or 'none'}`"
            ),
            (
                "- supplementary reference compare current-state rollup: "
                f"`{reference_compare_surface.get('current_mainline_status_path') or 'none'}`"
            ),
        ])
    if reference_program_compare_surface:
        authority_optional_group_lines.extend([
            (
                "- supplementary reference program compare gate (research-only, non-blocking): "
                f"`{reference_program_compare_surface.get('report_path') or 'none'}`"
            ),
            (
                "- supplementary reference program compare current-state rollup: "
                f"`{reference_program_compare_surface.get('current_mainline_status_path') or 'none'}`"
            ),
        ])
    if stat_snapshot_family_surface:
        authority_optional_group_lines.extend([
            (
                "- supplementary stat snapshot family surface (research-only, non-blocking): "
                f"`{stat_snapshot_family_surface.get('report_path') or 'none'}`"
            ),
            (
                "- supplementary stat snapshot family current-state rollup: "
                f"`{stat_snapshot_family_surface.get('current_mainline_status_path') or 'none'}`"
            ),
        ])
    if authority_optional_group_lines:
        lines[-2:-2] = authority_optional_group_lines + [""]
    if reasons:
        lines.extend([f"- {reason}" for reason in reasons])
    else:
        lines.append("- none")

    if timing:
        section_timings = timing.get("sections", {})
        lines.extend([
            "",
            "## Runtime Cost",
            "",
            f"- Total elapsed seconds: `{timing.get('total_elapsed_seconds')}`",
            f"- Blocking elapsed seconds: `{timing.get('blocking_elapsed_seconds')}`",
            f"- Non-blocking attachment elapsed seconds: `{timing.get('nonblocking_elapsed_seconds')}`",
        ])
        if section_timings:
            lines.extend([
                "",
                "| section | elapsed_seconds |",
                "| --- | --- |",
            ])
            for name, elapsed in sorted(section_timings.items()):
                lines.append(f"| {name} | {elapsed} |")
        if report.get("with_full_equivalence") and report.get("with_artifact_isolation"):
            lines.extend([
                "",
                "- Runtime hint: enabling `full_equivalence` and `artifact_isolation` replays additional research-only surfaces and can noticeably extend wall time.",
            ])

    lines.extend([
        "",
        "## Families",
        "",
        "| family | builder_run_id | toolchain_run_id | manifest_match | audit_ok |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in family_rows:
        lines.append(
            "| {family} | {builder_run_id} | {toolchain_run_id} | {manifest_match} | {audit_ok} |".format(
                family=row.get("family", "unknown"),
                builder_run_id=row.get("builder", {}).get("run_id") or "-",
                toolchain_run_id=row.get("toolchain", {}).get("run_id") or "-",
                manifest_match=row.get("audit", {}).get("manifest_match"),
                audit_ok=row.get("audit", {}).get("ok"),
            )
        )

    lines.extend([
        "",
        "## History",
        "",
        "| date | count | all_ok | healthy | drift_families | failed_families |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for entry in history_index.get("entries", []):
        lines.append(
            "| {date} | {count} | {all_ok} | {healthy} | {drift_families} | {failed_families} |".format(
                date=entry.get("date", "-"),
                count=entry.get("count", 0),
                all_ok=entry.get("all_ok"),
                healthy=entry.get("healthy"),
                drift_families=", ".join(entry.get("drift_families", [])) or "-",
                failed_families=", ".join(entry.get("failed_families", [])) or "-",
            )
        )

    if equivalence:
        lines.extend([
            "",
            "## Equivalence",
            "",
        ])
        _append_equivalence_block(lines, equivalence)

    if full_equivalence:
        lines.extend([
            "",
            "## Full All Equivalence Snapshot (Non-Blocking)",
            "",
        ])
        _append_equivalence_block(lines, full_equivalence, history=full_equivalence_history)

    if queue_equivalence:
        lines.extend([
            "",
            "## Queue Optional Equivalence (Non-Blocking)",
            "",
        ])
        _append_equivalence_block(lines, queue_equivalence)

    if nonqueue_optional_group_surfaces:
        lines.extend([
            "",
            "## Optional Group Equivalence (Non-Blocking)",
            "",
        ])
        for group, payload in nonqueue_optional_group_surfaces.items():
            _append_equivalence_block(lines, payload, group_label=group)
            lines.append("")

    if compare_surface:
        lines.extend([
            "",
            "## Supplementary Surfaces",
            "",
            f"- `compare.status = {compare_rollup.get('status')}`",
            f"- `compare.healthy = {compare_rollup.get('healthy')}`",
            f"- `compare.present = {compare_surface.get('present')}`",
            f"- `compare.gate_ok = {compare_surface.get('gate_ok')}`",
            f"- `compare.latest_date = {compare_surface.get('latest_date')}`",
            f"- `compare.stale = {compare_surface.get('stale')}`",
            f"- `compare.freshness_mode = {compare_surface.get('freshness_mode')}`",
            (
                "- `compare.effective_all_dates_ok = "
                f"{compare_surface.get('effective_all_dates_ok')}`"
            ),
            f"- `compare.report_path = {compare_surface.get('report_path')}`",
            (
                "- `compare.current_mainline_status_path = "
                f"{compare_surface.get('current_mainline_status_path')}`"
            ),
            f"- `compare.summary_md_path = {compare_surface.get('summary_md_path')}`",
        ])
        if compare_surface.get("load_error"):
            lines.append(f"- `compare.load_error = {compare_surface.get('load_error')}`")
    if reference_compare_surface:
        if not compare_surface:
            lines.extend([
                "",
                "## Supplementary Surfaces",
                "",
            ])
        lines.extend([
            f"- `reference_compare.status = {reference_compare_rollup.get('status')}`",
            f"- `reference_compare.healthy = {reference_compare_rollup.get('healthy')}`",
            f"- `reference_compare.present = {reference_compare_surface.get('present')}`",
            f"- `reference_compare.gate_ok = {reference_compare_surface.get('gate_ok')}`",
            f"- `reference_compare.latest_date = {reference_compare_surface.get('latest_date')}`",
            f"- `reference_compare.stale = {reference_compare_surface.get('stale')}`",
            (
                "- `reference_compare.freshness_mode = "
                f"{reference_compare_surface.get('freshness_mode')}`"
            ),
            (
                "- `reference_compare.effective_all_dates_ok = "
                f"{reference_compare_surface.get('effective_all_dates_ok')}`"
            ),
            (
                "- `reference_compare.report_path = "
                f"{reference_compare_surface.get('report_path')}`"
            ),
            (
                "- `reference_compare.current_mainline_status_path = "
                f"{reference_compare_surface.get('current_mainline_status_path')}`"
            ),
            (
                "- `reference_compare.summary_md_path = "
                f"{reference_compare_surface.get('summary_md_path')}`"
            ),
        ])
        if reference_compare_surface.get("load_error"):
            lines.append(
                f"- `reference_compare.load_error = {reference_compare_surface.get('load_error')}`"
            )
    if reference_program_compare_surface:
        if not compare_surface and not reference_compare_surface:
            lines.extend([
                "",
                "## Supplementary Surfaces",
                "",
            ])
        lines.extend([
            (
                "- `reference_program_compare.status = "
                f"{reference_program_compare_rollup.get('status')}`"
            ),
            (
                "- `reference_program_compare.healthy = "
                f"{reference_program_compare_rollup.get('healthy')}`"
            ),
            (
                "- `reference_program_compare.present = "
                f"{reference_program_compare_surface.get('present')}`"
            ),
            (
                "- `reference_program_compare.gate_ok = "
                f"{reference_program_compare_surface.get('gate_ok')}`"
            ),
            (
                "- `reference_program_compare.latest_date = "
                f"{reference_program_compare_surface.get('latest_date')}`"
            ),
            (
                "- `reference_program_compare.stale = "
                f"{reference_program_compare_surface.get('stale')}`"
            ),
            (
                "- `reference_program_compare.freshness_mode = "
                f"{reference_program_compare_surface.get('freshness_mode')}`"
            ),
            (
                "- `reference_program_compare.effective_all_dates_ok = "
                f"{reference_program_compare_surface.get('effective_all_dates_ok')}`"
            ),
            (
                "- `reference_program_compare.report_path = "
                f"{reference_program_compare_surface.get('report_path')}`"
            ),
            (
                "- `reference_program_compare.current_mainline_status_path = "
                f"{reference_program_compare_surface.get('current_mainline_status_path')}`"
            ),
            (
                "- `reference_program_compare.summary_md_path = "
                f"{reference_program_compare_surface.get('summary_md_path')}`"
            ),
        ])
        if reference_program_compare_surface.get("load_error"):
            lines.append(
                "- `reference_program_compare.load_error = "
                f"{reference_program_compare_surface.get('load_error')}`"
            )
    if stat_snapshot_family_surface:
        if not compare_surface and not reference_compare_surface and not reference_program_compare_surface:
            lines.extend([
                "",
                "## Supplementary Surfaces",
                "",
            ])
        lines.extend([
            (
                "- `stat_snapshot_family.status = "
                f"{stat_snapshot_family_rollup.get('status')}`"
            ),
            (
                "- `stat_snapshot_family.healthy = "
                f"{stat_snapshot_family_rollup.get('healthy')}`"
            ),
            (
                "- `stat_snapshot_family.present = "
                f"{stat_snapshot_family_surface.get('present')}`"
            ),
            (
                "- `stat_snapshot_family.gate_ok = "
                f"{stat_snapshot_family_surface.get('gate_ok')}`"
            ),
            (
                "- `stat_snapshot_family.latest_date = "
                f"{stat_snapshot_family_surface.get('latest_date')}`"
            ),
            (
                "- `stat_snapshot_family.stale = "
                f"{stat_snapshot_family_surface.get('stale')}`"
            ),
            (
                "- `stat_snapshot_family.freshness_mode = "
                f"{stat_snapshot_family_surface.get('freshness_mode')}`"
            ),
            (
                "- `stat_snapshot_family.effective_all_dates_ok = "
                f"{stat_snapshot_family_surface.get('effective_all_dates_ok')}`"
            ),
            (
                "- `stat_snapshot_family.selector_count = "
                f"{stat_snapshot_family_surface.get('selector_count')}`"
            ),
            (
                "- `stat_snapshot_family.covered_selector_count = "
                f"{stat_snapshot_family_surface.get('covered_selector_count')}`"
            ),
            (
                "- `stat_snapshot_family.report_path = "
                f"{stat_snapshot_family_surface.get('report_path')}`"
            ),
            (
                "- `stat_snapshot_family.current_mainline_status_path = "
                f"{stat_snapshot_family_surface.get('current_mainline_status_path')}`"
            ),
            (
                "- `stat_snapshot_family.summary_md_path = "
                f"{stat_snapshot_family_surface.get('summary_md_path')}`"
            ),
        ])
        for row in list(stat_snapshot_family_surface.get("selector_rows") or []):
            lines.append(
                "- `stat_snapshot_family.{name}.reference_ready = {ready}`".format(
                    name=row.get("selector_name"),
                    ready=row.get("reference_ready"),
                )
            )
        if stat_snapshot_family_surface.get("load_error"):
            lines.append(
                "- `stat_snapshot_family.load_error = "
                f"{stat_snapshot_family_surface.get('load_error')}`"
            )

    if artifact_isolation:
        lines.extend([
            "",
            "## Artifact Isolation (Non-Blocking)",
            "",
            f"- All OK: `{artifact_isolation.get('all_ok')}`",
            f"- Summary path: `{artifact_isolation.get('summary_path')}`",
            f"- History path: `{artifact_isolation_history.get('summary_path') if artifact_isolation_history else 'none'}`",
            f"- History latest date: `{artifact_isolation_history.get('latest_date') if artifact_isolation_history else 'none'}`",
            f"- History entry count: `{artifact_isolation_history.get('entry_count') if artifact_isolation_history else 0}`",
            "",
            "| surface | canonical_unchanged | subset_surface | subset_summary_path |",
            "| --- | --- | --- | --- |",
        ])
        for name, row in sorted(artifact_isolation.get("surfaces", {}).items()):
            lines.append(
                "| {surface} | {canonical_unchanged} | {subset_surface} | {subset_summary_path} |".format(
                    surface=name,
                    canonical_unchanged=row.get("canonical_unchanged"),
                    subset_surface=row.get("subset_surface"),
                    subset_summary_path=row.get("subset_summary_path"),
                )
            )

    if abi_audit:
        lines.extend([
            "",
            "## ABI Audit",
            "",
            f"- Artifact role: `{abi_audit.get('artifact_role')}`",
            f"- All OK: `{abi_audit.get('all_ok')}`",
            f"- Summary path: `{abi_audit.get('summary_path')}`",
            f"- generated_include_matches_checked_in: `{abi_audit.get('generated_include_matches_checked_in')}`",
            f"- toolchain_all_ok: `{abi_audit.get('toolchain_all_ok')}`",
            "",
            "| program | main_uses_abi_bridge | abi_bridge_matches_authority | ok |",
            "| --- | --- | --- | --- |",
        ])
        for row in abi_audit.get("toolchain_programs", []):
            lines.append(
                "| {program} | {main_uses_abi_bridge} | {abi_bridge_matches_authority} | {ok} |".format(
                    program=row.get("program", "unknown"),
                    main_uses_abi_bridge=row.get("main_uses_abi_bridge"),
                    abi_bridge_matches_authority=row.get("abi_bridge_matches_authority"),
                    ok=row.get("ok"),
                )
            )

    _atomic_write_text(resolved_output_path, "\n".join(lines) + "\n")
    return resolved_output_path


def _observer_rollup_from_history(history: dict[str, Any] | None,
                                  *,
                                  live_surface: dict[str, Any] | None = None) -> dict[str, Any]:
    history = history or {}
    live_surface = live_surface or {}
    canonical_surface = live_surface.get("canonical_surface")
    refresh_mode = history.get("refresh_mode")
    if refresh_mode is None:
        refresh_mode = live_surface.get("refresh_mode")
    effective_entry_count = history.get("effective_entry_count")
    if effective_entry_count is None:
        effective_entry_count = live_surface.get("effective_entry_count")
    effective_all_dates_ok = history.get("effective_all_dates_ok")
    if effective_all_dates_ok is None:
        effective_all_dates_ok = live_surface.get("effective_all_dates_ok")
    return {
        "enabled": bool(history) or bool(live_surface),
        "summary_path": live_surface.get("summary_path"),
        "canonical_surface": None if canonical_surface is None else bool(canonical_surface),
        "surface": None if canonical_surface is None else _surface_label(canonical_surface),
        "count": live_surface.get("count"),
        "all_ok": live_surface.get("all_ok"),
        "history_path": history.get("summary_path"),
        "history_contract": history.get("history_contract"),
        "latest_summary_path": history.get("latest_summary_path"),
        "latest_date": history.get("latest_date"),
        "entry_count": history.get("entry_count", 0),
        "refresh_mode": refresh_mode,
        "effective_entry_count": effective_entry_count,
        "effective_all_dates_ok": effective_all_dates_ok,
        "all_ok_latest": history.get("all_ok_latest"),
        "all_dates_ok": history.get("all_dates_ok"),
        "first_fail_date": history.get("first_fail_date"),
        "latest_recovered_date": history.get("latest_recovered_date"),
        "excluded_entry_count": history.get("excluded_entry_count", 0),
    }


def _optional_history_surface(*,
                              group: str = "queue_optional",
                              live_surface: dict[str, Any] | None = None,
                              lab_root: Path = LAB_ROOT) -> dict[str, Any] | None:
    history_path = stable_reference_path(f"{group.replace('_', '-')}-equivalence-history", lab_root=lab_root)
    has_dated_inputs = _optional_group_has_dated_inputs(group, lab_root=lab_root)
    expected_refresh_mode = _optional_history_refresh_mode(group, lab_root=lab_root)
    compact_since_latest_recovery = expected_refresh_mode == "compact_latest_recovery"
    if history_path.exists():
        existing_history = _load_json(history_path)
        latest_surface, latest_surface_path = _latest_optional_group_equivalence_surface(
            group=group,
            lab_root=lab_root,
        )
        latest_payload = live_surface or latest_surface or {}
        latest_summary_path = (
            str(latest_surface_path)
            if latest_surface_path is not None
            else latest_payload.get("summary_path")
        )
        latest_key = _optional_surface_freshness_key(
            latest_payload,
            summary_path=latest_summary_path,
        ) if latest_payload else ("", float("-inf"), float("-inf"))
        history_key = (
            str(existing_history.get("latest_date") or ""),
            _generated_utc_timestamp(
                next(
                    (
                        row.get("generated_utc")
                        for row in existing_history.get("entries", [])
                        if row.get("summary_path") == existing_history.get("latest_summary_path")
                    ),
                    None,
                )
            ),
            _path_mtime(Path(str(existing_history.get("latest_summary_path"))))
            if existing_history.get("latest_summary_path")
            else float("-inf"),
        )
        existing_refresh_mode = str(existing_history.get("refresh_mode") or "dated_scan")
        refresh_mode_matches = existing_refresh_mode == expected_refresh_mode
        if (
            existing_history.get("latest_summary_path")
            and history_key >= latest_key
            and refresh_mode_matches
        ):
            return existing_history
    if live_surface or has_dated_inputs:
        return refresh_optional_equivalence_history(
            group=group,
            optional_equivalence=live_surface,
            compact_since_latest_recovery=compact_since_latest_recovery,
            lab_root=lab_root,
            output_path=history_path,
        )
    if history_path.exists():
        return _load_json(history_path)
    return None


def _latest_optional_admission_audit(*,
                                     group: str = "queue_optional",
                                     lab_root: Path = LAB_ROOT) -> tuple[dict[str, Any] | None, Path | None]:
    audit_path = _latest_dated_reference(f"*-{group.replace('_', '-')}-admission-audit.json", lab_root=lab_root)
    if audit_path is None or not audit_path.exists():
        return None, None
    return _load_json(audit_path), audit_path


def _optional_admission_effective_freshness(admission: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(admission or {})
    freshness_mode = payload.get("group_history_freshness_mode")
    effective_entry_count = payload.get("group_history_effective_entry_count")
    effective_all_dates_ok = payload.get("group_history_effective_all_dates_ok")
    if freshness_mode is None:
        freshness_mode = payload.get("queue_history_freshness_mode")
    if effective_entry_count is None:
        effective_entry_count = payload.get("queue_history_effective_entry_count")
    if effective_all_dates_ok is None:
        effective_all_dates_ok = payload.get("queue_history_effective_all_dates_ok")
    return {
        "freshness_mode": freshness_mode,
        "effective_entry_count": effective_entry_count,
        "effective_all_dates_ok": effective_all_dates_ok,
    }


def _equivalence_surface_failure_summary(surface: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, list[str]], list[str]]:
    family_paths: dict[str, str] = {}
    surface_failures: dict[str, list[str]] = {}
    failing_reason_ids: list[str] = []
    for row in list((surface or {}).get("families", []) or []):
        family = str(row.get("family") or "").strip()
        if not family:
            continue
        summary_path = row.get("summary_path")
        if summary_path:
            family_paths[family] = str(summary_path)
        reasons = [str(reason) for reason in list(row.get("gate_reasons", []) or []) if str(reason).strip()]
        if reasons:
            surface_failures[family] = reasons
            failing_reason_ids.extend(reasons)
    return family_paths, surface_failures, sorted(set(failing_reason_ids))


def build_sidecar_observer_summary(report: dict[str, Any],
                                   *,
                                   output_path: Path | None = None,
                                   lab_root: Path = LAB_ROOT) -> Path:
    resolved_output_path = output_path or stable_reference_path("nightly-sidecar-observer-summary", lab_root=lab_root)
    optional_group_surfaces = _report_optional_group_surfaces(report)
    supplementary_surfaces = _report_supplementary_surfaces(report, lab_root=lab_root)
    supplementary_surface_history_path = Path(
        report.get("supplementary_surface_history_path")
        or stable_reference_path("supplementary-surface-history", lab_root=lab_root)
    )
    supplementary_surface_histories = {}
    if supplementary_surface_history_path.exists():
        supplementary_history_payload = _load_json(supplementary_surface_history_path)
        supplementary_surface_histories = {
            name: dict(payload or {})
            for name, payload in dict(supplementary_history_payload.get("surfaces", {}) or {}).items()
            if isinstance(payload, dict)
        }
    supplementary_surface_rollups = {
        name: {
            **_supplementary_surface_rollup(name, payload, lab_root=lab_root),
            **(
                {
                    "history_contract": supplementary_surface_histories.get(name, {}).get("history_contract"),
                    "history_path": supplementary_surface_histories.get(name, {}).get("history_path"),
                    "entry_count": supplementary_surface_histories.get(name, {}).get("entry_count"),
                    "latest_recovered_date": supplementary_surface_histories.get(name, {}).get("latest_recovered_date"),
                    "all_dates_ok": supplementary_surface_histories.get(name, {}).get("all_dates_ok"),
                    "effective_entry_count": supplementary_surface_histories.get(name, {}).get("effective_entry_count"),
                }
                if supplementary_surface_histories.get(name)
                else {}
            ),
        }
        for name, payload in supplementary_surfaces.items()
    }
    abi_audit = dict(report.get("abi_audit") or {})
    preferred_full_equivalence_history = (
        report.get("observer_full_equivalence_history")
        or report.get("full_equivalence_history")
    )
    optional_group_rollups: dict[str, dict[str, Any]] = {}
    for group in sorted(_mainline_optional_groups(lab_root=lab_root)):
        live_surface = dict(optional_group_surfaces.get(group) or {})
        history = _optional_history_surface(
            group=group,
            live_surface=live_surface or None,
            lab_root=lab_root,
        )
        admission, admission_path = _latest_optional_admission_audit(
            group=group,
            lab_root=lab_root,
        )
        effective_freshness = _optional_admission_effective_freshness(admission)
        if (
            effective_freshness["freshness_mode"] is None
            or effective_freshness["effective_entry_count"] is None
            or effective_freshness["effective_all_dates_ok"] is None
        ):
            computed_mode = effective_freshness["freshness_mode"] or str(
                _mainline_optional_group_promotion_contract(group, lab_root=lab_root).get(
                    "multi_date_freshness_mode"
                )
                or "all_dates"
            )
            computed_freshness = _optional_history_freshness_rollup(
                history or {},
                mode=computed_mode,
            )
            effective_freshness["freshness_mode"] = computed_mode
            if effective_freshness["effective_entry_count"] is None:
                effective_freshness["effective_entry_count"] = computed_freshness["effective_entry_count"]
            if effective_freshness["effective_all_dates_ok"] is None:
                effective_freshness["effective_all_dates_ok"] = computed_freshness["effective_all_dates_ok"]
        rollup = _observer_rollup_from_history(
            history,
            live_surface=live_surface,
        )
        rollup.update(
            {
                "enabled": bool(rollup.get("enabled")) or bool(admission),
                "admission_summary_path": (
                    str(admission_path)
                    if admission_path is not None
                    else (admission or {}).get("summary_path")
                ),
                "promotion_ready": (admission or {}).get("promotion_ready"),
                "explicit_review_ok": (admission or {}).get("explicit_review_ok"),
                "blocking": (admission or {}).get("blocking"),
                **effective_freshness,
            }
        )
        optional_group_rollups[group] = rollup
    queue_rollup = dict(optional_group_rollups.get("queue_optional") or {})
    payload = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_SIDECAR_OBSERVER_SUMMARY,
            scope="observer_surface_only",
            producer="riscv_snn_lab.build_sidecar_observer_summary",
        ),
        "gate_name": report.get("gate_name"),
        "gate_version": report.get("gate_version"),
        "gate_ok": bool(report.get("gate_ok")),
        "generated_from": report.get("generated_utc"),
        "authority_entrypoint": {
            "summary_path": report.get("report_path")
            or str(stable_reference_path("nightly-sidecar-report", lab_root=lab_root)),
            "artifact_role": report.get("artifact_role"),
            "authority_scope": report.get("authority_scope"),
            "policy": "read_stable_sidecar_report_then_follow_optional_surfaces",
        },
        "required_families": list(report.get("required_families", []) or []),
        "latest_history_date": report.get("history_index", {}).get("latest_date"),
        "timing": dict(report.get("timing", {}) or {}),
        "optional_group_rollups": optional_group_rollups,
        "optional_surfaces": {
            "full_equivalence": _observer_rollup_from_history(
                preferred_full_equivalence_history,
                live_surface=report.get("full_equivalence"),
            ),
            "artifact_isolation": _observer_rollup_from_history(
                report.get("artifact_isolation_history"),
                live_surface=report.get("artifact_isolation"),
            ),
            "queue_equivalence": queue_rollup,
            "abi_audit": {
                "enabled": bool(abi_audit),
                "summary_path": abi_audit.get("summary_path"),
                "all_ok": abi_audit.get("all_ok"),
                "toolchain_all_ok": abi_audit.get("toolchain_all_ok"),
            },
        },
        "supplementary_surfaces": supplementary_surfaces,
        "supplementary_surface_rollups": supplementary_surface_rollups,
        "supplementary_surface_history_path": str(supplementary_surface_history_path),
        "supplementary_surface_histories": supplementary_surface_histories,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, payload)
    return resolved_output_path


def run_nightly(*,
                builder_programs: list[str] | None = None,
                toolchain_programs: list[str] | None = None,
                register: bool = True,
                protocol: bool = True,
                builder_summary_path: Path | None = None,
                toolchain_summary_path: Path | None = None,
                toolchain_audit_summary_path: Path | None = None,
                summary_path: Path | None = None,
                lab_root: Path = LAB_ROOT,
                runner: Runner = run_command) -> dict[str, Any]:
    resolved_builder_programs = list(builder_programs) if builder_programs is not None else matrix_programs("builder")
    resolved_toolchain_programs = (
        list(toolchain_programs) if toolchain_programs is not None else matrix_programs("toolchain")
    )
    canonical_surface = _is_canonical_nightly_surface(
        resolved_builder_programs,
        resolved_toolchain_programs,
    )
    resolved_builder_summary_path = builder_summary_path or _default_matrix_summary_path(
        "builder",
        resolved_builder_programs,
        lab_root=lab_root,
    )
    resolved_toolchain_summary_path = toolchain_summary_path or _default_matrix_summary_path(
        "toolchain",
        resolved_toolchain_programs,
        lab_root=lab_root,
    )
    resolved_toolchain_audit_summary_path = toolchain_audit_summary_path or _default_audit_summary_path(
        "toolchain",
        resolved_toolchain_programs,
        lab_root=lab_root,
    )
    resolved_summary_path = summary_path or _default_nightly_summary_path(
        resolved_builder_programs,
        resolved_toolchain_programs,
        lab_root=lab_root,
    )
    builder_summary = run_matrix(
        "builder",
        programs=resolved_builder_programs,
        register=register,
        summary_path=resolved_builder_summary_path,
        lab_root=lab_root,
        runner=runner,
    )
    toolchain_summary = run_matrix(
        "toolchain",
        programs=resolved_toolchain_programs,
        register=register,
        summary_path=resolved_toolchain_summary_path,
        lab_root=lab_root,
        runner=runner,
    )
    toolchain_audit = audit_programs(
        "toolchain",
        programs=resolved_toolchain_programs,
        protocol=protocol,
        summary_path=resolved_toolchain_audit_summary_path,
        lab_root=lab_root,
        runner=runner,
    )
    return build_nightly_index(
        builder_summary,
        toolchain_summary,
        toolchain_audit,
        requested_builder_programs=resolved_builder_programs,
        requested_toolchain_programs=resolved_toolchain_programs,
        canonical_surface=canonical_surface,
        output_path=resolved_summary_path,
        lab_root=lab_root,
    )


def run_ci_sidecar(*,
                   builder_programs: list[str] | None = None,
                   toolchain_programs: list[str] | None = None,
                   min_count: int | None = None,
                   register: bool = True,
                   protocol: bool = True,
                   with_equivalence: bool = False,
                   with_full_equivalence: bool = False,
                   with_optional_groups: list[str] | None = None,
                   with_queue_equivalence: bool = False,
                   with_abi_audit: bool = False,
                   with_artifact_isolation: bool = False,
                   summary_path: Path | None = None,
                   history_path: Path | None = None,
                   report_path: Path | None = None,
                   lab_root: Path = LAB_ROOT,
                   runner: Runner = run_command) -> dict[str, Any]:
    total_start = time.monotonic()
    section_timings: dict[str, float] = {}

    start = time.monotonic()
    nightly_index = run_nightly(
        builder_programs=builder_programs,
        toolchain_programs=toolchain_programs,
        register=register,
        protocol=protocol,
        summary_path=summary_path,
        lab_root=lab_root,
        runner=runner,
    )
    section_timings["nightly_elapsed_seconds"] = round(time.monotonic() - start, 3)
    start = time.monotonic()
    history_index = refresh_history_index(
        lab_root=lab_root,
        output_path=history_path,
    )
    section_timings["history_elapsed_seconds"] = round(time.monotonic() - start, 3)
    required_families = authority_required_families(
        builder_programs=builder_programs,
        toolchain_programs=toolchain_programs,
    )
    gate = evaluate_nightly_gate(
        nightly_index,
        required_families=required_families,
        min_count=min_count,
    )
    known_optional_groups = _mainline_optional_groups(lab_root=lab_root)
    requested_optional_groups = _sorted_unique(
        [*(with_optional_groups or []), *(["queue_optional"] if with_queue_equivalence else [])]
    )
    unknown_optional_groups = [group for group in requested_optional_groups if group not in known_optional_groups]
    if unknown_optional_groups:
        raise ValueError(
            "unknown sidecar optional group(s): " + ", ".join(unknown_optional_groups)
        )
    queue_requested = "queue_optional" in requested_optional_groups
    equivalence = None
    full_equivalence = None
    full_equivalence_history = None
    observer_full_equivalence_history = None
    optional_group_surfaces: dict[str, dict[str, Any]] = {}
    artifact_isolation = None
    artifact_isolation_history = None
    abi_audit = None
    if with_equivalence:
        start = time.monotonic()
        equivalence = run_equiv_matrix(
            families=required_families,
            lab_root=lab_root,
            runner=runner,
        )
        section_timings["equivalence_elapsed_seconds"] = round(time.monotonic() - start, 3)
        if not bool(equivalence.get("all_ok")):
            gate["reasons"].append("equivalence matrix all_ok is false")
        equivalence_families = _sorted_unique([row.get("family") for row in equivalence.get("families", [])])
        missing_equiv_families = [family for family in required_families if family not in equivalence_families]
        if missing_equiv_families:
            gate["reasons"].append(
                "equivalence missing required families: " + ", ".join(missing_equiv_families)
            )
        gate["gate_ok"] = not gate["reasons"]
    if with_full_equivalence:
        start = time.monotonic()
        full_equivalence = run_equiv_matrix(
            families=None,
            group="all",
            lab_root=lab_root,
            runner=runner,
        )
        section_timings["full_equivalence_elapsed_seconds"] = round(time.monotonic() - start, 3)
        full_equivalence_history = refresh_full_equivalence_history(
            full_equivalence=full_equivalence,
            lab_root=lab_root,
        )
        observer_full_equivalence_history = refresh_observer_full_equivalence_history(
            full_equivalence=full_equivalence,
            lab_root=lab_root,
        )
    optional_group_elapsed_seconds = 0.0
    for group in requested_optional_groups:
        start = time.monotonic()
        optional_group_surfaces[group] = run_equiv_matrix(
            families=None,
            group=group,
            lab_root=lab_root,
            runner=runner,
        )
        elapsed = round(time.monotonic() - start, 3)
        optional_group_elapsed_seconds += elapsed
        section_timings[f"{group}_equivalence_elapsed_seconds"] = elapsed
        if group == "queue_optional":
            section_timings["queue_equivalence_elapsed_seconds"] = elapsed
    if requested_optional_groups:
        section_timings["optional_group_equivalence_elapsed_seconds"] = round(optional_group_elapsed_seconds, 3)
    if with_artifact_isolation:
        start = time.monotonic()
        artifact_isolation = run_artifact_isolation_check(
            builder_programs=builder_programs,
            toolchain_programs=toolchain_programs,
            lab_root=lab_root,
            runner=runner,
        )
        section_timings["artifact_isolation_elapsed_seconds"] = round(time.monotonic() - start, 3)
        artifact_isolation_history = refresh_artifact_isolation_history(
            artifact_isolation,
            lab_root=lab_root,
        )
    if with_abi_audit:
        start = time.monotonic()
        abi_audit = audit_abi_surface(
            lab_root=lab_root,
        )
        section_timings["abi_audit_elapsed_seconds"] = round(time.monotonic() - start, 3)

    blocking_elapsed_seconds = round(
        sum(
            section_timings.get(name, 0.0)
            for name in ("nightly_elapsed_seconds", "history_elapsed_seconds", "equivalence_elapsed_seconds")
        ),
        3,
    )
    nonblocking_elapsed_seconds = round(
        sum(
            section_timings.get(name, 0.0)
            for name in (
                "full_equivalence_elapsed_seconds",
                "artifact_isolation_elapsed_seconds",
                "abi_audit_elapsed_seconds",
            )
        ) + optional_group_elapsed_seconds,
        3,
    )
    timing = {
        "total_elapsed_seconds": round(time.monotonic() - total_start, 3),
        "blocking_elapsed_seconds": blocking_elapsed_seconds,
        "nonblocking_elapsed_seconds": nonblocking_elapsed_seconds,
        "sections": section_timings,
    }

    resolved_report_path = report_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    resolved_observer_summary_path = stable_reference_path("nightly-sidecar-observer-summary", lab_root=lab_root)
    resolved_summary_md_path = stable_markdown_path("nightly-sidecar-summary", lab_root=lab_root)
    derived_from = [ARTIFACT_ROLE_DATED_NIGHTLY_INDEX, ARTIFACT_ROLE_STABLE_HISTORY_ROLLUP]
    if equivalence is not None or full_equivalence is not None:
        if ARTIFACT_ROLE_DATED_EQUIV_MATRIX not in derived_from:
            derived_from.append(ARTIFACT_ROLE_DATED_EQUIV_MATRIX)
    if optional_group_surfaces:
        if ARTIFACT_ROLE_DATED_EQUIV_MATRIX not in derived_from:
            derived_from.append(ARTIFACT_ROLE_DATED_EQUIV_MATRIX)
    if artifact_isolation is not None:
        derived_from.append(ARTIFACT_ROLE_STABLE_ARTIFACT_ISOLATION_CHECK)
    if abi_audit is not None:
        derived_from.append(ARTIFACT_ROLE_DATED_ABI_AUDIT)
    supplementary_surfaces = _supplementary_surfaces(lab_root=lab_root)
    report = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE,
            scope="experimental_gate_authority",
            producer="riscv_snn_lab.run_ci_sidecar",
        ),
        "gate_name": gate["gate_name"],
        "gate_version": gate["gate_version"],
        "gate_ok": gate["gate_ok"],
        "reasons": gate["reasons"],
        "derived_from": derived_from,
        "required_families": gate["required_families"],
        "missing_families": gate["missing_families"],
        "unexpected_families": gate["unexpected_families"],
        "failed_families": gate["failed_families"],
        "drift_families": gate["drift_families"],
        "min_count": gate["min_count"],
        "actual_count": gate["actual_count"],
        "with_equivalence": with_equivalence,
        "with_full_equivalence": with_full_equivalence,
        "with_optional_groups": requested_optional_groups,
        "with_queue_equivalence": queue_requested,
        "with_abi_audit": with_abi_audit,
        "with_artifact_isolation": with_artifact_isolation,
        "nightly_index": nightly_index,
        "optional_group_surfaces": optional_group_surfaces,
        "equivalence": equivalence,
        "full_equivalence": full_equivalence,
        "full_equivalence_history": full_equivalence_history,
        "observer_full_equivalence_history": observer_full_equivalence_history,
        "queue_equivalence": optional_group_surfaces.get("queue_optional"),
        "artifact_isolation": artifact_isolation,
        "artifact_isolation_history": artifact_isolation_history,
        "abi_audit": abi_audit,
        "supplementary_surfaces": supplementary_surfaces,
        "history_index": history_index,
        "timing": timing,
        "report_path": str(resolved_report_path),
        "observer_summary_path": str(resolved_observer_summary_path),
        "summary_md_path": str(resolved_summary_md_path),
        "current_mainline_status_path": None,
    }
    _write_json(resolved_report_path, report)
    _refresh_derived_stable_surfaces(
        sidecar_path=resolved_report_path,
        observer_summary_path=resolved_observer_summary_path,
        lab_root=lab_root,
    )
    return _load_json(resolved_report_path)


def run_artifact_isolation_check(*,
                                 builder_programs: list[str] | None = None,
                                 toolchain_programs: list[str] | None = None,
                                 report_path: Path | None = None,
                                 lab_root: Path = LAB_ROOT,
                                 runner: Runner = run_command) -> dict[str, Any]:
    resolved_builder_programs = (
        list(builder_programs[:1])
        if builder_programs is not None
        else [matrix_programs("builder")[0]]
    )
    resolved_toolchain_programs = (
        list(toolchain_programs[:1])
        if toolchain_programs is not None
        else [matrix_programs("toolchain")[0]]
    )
    canonical_paths = {
        "builder": _default_matrix_summary_path("builder", matrix_programs("builder"), lab_root=lab_root),
        "toolchain": _default_matrix_summary_path("toolchain", matrix_programs("toolchain"), lab_root=lab_root),
        "toolchain_audit": _default_audit_summary_path("toolchain", matrix_programs("toolchain"), lab_root=lab_root),
        "nightly": _default_nightly_summary_path(matrix_programs("builder"), matrix_programs("toolchain"), lab_root=lab_root),
    }
    before_states = {name: _path_state(path) for name, path in canonical_paths.items()}

    builder_summary = run_matrix(
        "builder",
        programs=resolved_builder_programs,
        summary_path=_default_matrix_summary_path("builder", resolved_builder_programs, lab_root=lab_root),
        lab_root=lab_root,
        runner=runner,
    )
    toolchain_summary = run_matrix(
        "toolchain",
        programs=resolved_toolchain_programs,
        summary_path=_default_matrix_summary_path("toolchain", resolved_toolchain_programs, lab_root=lab_root),
        lab_root=lab_root,
        runner=runner,
    )
    audit_summary = audit_programs(
        "toolchain",
        programs=resolved_toolchain_programs,
        protocol=False,
        summary_path=_default_audit_summary_path("toolchain", resolved_toolchain_programs, lab_root=lab_root),
        lab_root=lab_root,
        runner=runner,
    )
    nightly_summary = run_nightly(
        builder_programs=resolved_builder_programs,
        toolchain_programs=resolved_toolchain_programs,
        register=False,
        protocol=False,
        summary_path=_default_nightly_summary_path(
            resolved_builder_programs,
            resolved_toolchain_programs,
            lab_root=lab_root,
        ),
        lab_root=lab_root,
        runner=runner,
    )

    subset_results = {
        "builder": builder_summary,
        "toolchain": toolchain_summary,
        "toolchain_audit": audit_summary,
        "nightly": nightly_summary,
    }
    surfaces: dict[str, dict[str, Any]] = {}
    for name, canonical_path in canonical_paths.items():
        after_state = _path_state(canonical_path)
        subset_summary = subset_results[name]
        subset_summary_path = Path(str(subset_summary.get("summary_path")))
        surfaces[name] = {
            "canonical_path": str(canonical_path),
            "canonical_exists_before": before_states[name]["exists"],
            "canonical_exists_after": after_state["exists"],
            "canonical_mtime_ns_before": before_states[name]["mtime_ns"],
            "canonical_mtime_ns_after": after_state["mtime_ns"],
            "canonical_unchanged": before_states[name] == after_state,
            "subset_summary_path": str(subset_summary_path),
            "subset_path_differs_from_canonical": subset_summary_path != canonical_path,
            "subset_canonical_surface": bool(subset_summary.get("canonical_surface")),
            "subset_surface": _surface_label(subset_summary.get("canonical_surface")),
        }

    all_ok = all(
        row["canonical_unchanged"]
        and row["subset_path_differs_from_canonical"]
        and not row["subset_canonical_surface"]
        for row in surfaces.values()
    )
    resolved_report_path = report_path or stable_reference_path("artifact-isolation-report", lab_root=lab_root)
    report = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_ARTIFACT_ISOLATION_CHECK,
            scope="artifact_surface_isolation_observer",
            producer="riscv_snn_lab.run_artifact_isolation_check",
        ),
        "all_ok": all_ok,
        "builder_programs": resolved_builder_programs,
        "toolchain_programs": resolved_toolchain_programs,
        "surfaces": surfaces,
        "summary_path": str(resolved_report_path),
    }
    _write_json(resolved_report_path, report)
    return report


def _validation_check_id(line: str, outcome: str) -> str | None:
    match = re.match(rf"^\[val\]\s+{re.escape(outcome)}\s+([^:]+):", line)
    if match:
        return match.group(1).strip()
    return None


def _equiv_validation_summary(family: str,
                              role: str,
                              validation: dict[str, Any]) -> dict[str, Any]:
    waiver = EQUIV_VALIDATION_FAIL_WAIVERS.get((family, role), {})
    allowed_fail_checks = list(waiver.get("allowed_fail_checks", []))
    raw_summary = str(validation.get("summary", "unknown"))
    raw_fail_checks = list(validation.get("fail_checks", []))
    waived_fail_checks = [check for check in raw_fail_checks if check in allowed_fail_checks]
    blocked_fail_checks = [check for check in raw_fail_checks if check not in allowed_fail_checks]

    if raw_summary in {"smoke_failed", "preflight_failed"}:
        ok = False
        summary = raw_summary
    elif raw_summary == "failed":
        ok = bool(raw_fail_checks) and not blocked_fail_checks and len(waived_fail_checks) == len(raw_fail_checks)
        summary = "passed_with_waiver" if ok else "failed"
    else:
        ok = raw_summary != "failed"
        summary = raw_summary

    return {
        "summary": summary,
        "ok": ok,
        "raw_summary": raw_summary,
        "waiver_name": waiver.get("name"),
        "waiver_applied": bool(waived_fail_checks),
        "allowed_fail_checks": allowed_fail_checks,
        "waived_fail_checks": waived_fail_checks,
        "blocked_fail_checks": blocked_fail_checks,
    }


def _validation_summary(run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "validation.log"
    if not log_path.exists():
        return {
            "summary": "not_run",
            "pass_lines": [],
            "warn_lines": [],
            "fail_lines": [],
            "pass_checks": [],
            "warn_checks": [],
            "fail_checks": [],
        }
    lines = log_path.read_text(encoding="utf-8").splitlines()
    summary = "unknown"
    passes: list[str] = []
    warns: list[str] = []
    fails: list[str] = []
    pass_checks: list[str] = []
    warn_checks: list[str] = []
    fail_checks: list[str] = []
    for line in lines:
        stripped = line.strip()
        pass_check = _validation_check_id(stripped, "PASS")
        warn_check = _validation_check_id(stripped, "WARN")
        fail_check = _validation_check_id(stripped, "FAIL")
        if pass_check:
            pass_checks.append(pass_check)
        if " PASS " in line and (
            "contracts.present" in line or
            "contracts.gas_semantic_ready_before_commit" in line or
            "contracts.gas_semantic_drain_before_scatter" in line or
            "snn_rx.packet_accounting" in line or
            "snn_tx.nonzero" in line or
            "memory.nonzero" in line
        ):
            passes.append(stripped)
        if warn_check:
            warns.append(stripped)
            warn_checks.append(warn_check)
        if fail_check:
            fails.append(stripped)
            fail_checks.append(fail_check)
        if " SUMMARY " in line:
            if "fail=0 warn=0" in line:
                summary = "passed"
            elif "fail=0" in line:
                summary = "passed_with_warning"
            else:
                summary = "failed"
    return {
        "summary": summary,
        "pass_lines": passes,
        "warn_lines": warns,
        "fail_lines": fails,
        "pass_checks": pass_checks,
        "warn_checks": warn_checks,
        "fail_checks": fail_checks,
    }


def _surface_from_run_dir(run_dir: Path) -> dict[str, Any]:
    resolved_run_dir = run_dir.resolve()
    summary = _load_json(resolved_run_dir / "essential_summary_mesh.json")
    meta = _load_json(resolved_run_dir / "meta.json")
    input_spec = _load_json(resolved_run_dir / "inputs" / "spec.json")
    validation = _validation_summary(resolved_run_dir)
    mesh_stats = _extract_mesh_stat_totals(resolved_run_dir / "mesh_stats.csv")
    return {
        "run_dir": str(resolved_run_dir),
        "summary": summary,
        "meta": meta,
        "input_spec": input_spec,
        "validation": validation,
        "runtime_stats": {
            name: mesh_stats.get(name)
            for name in RUNTIME_BRIDGE_RUNTIME_STATS
            if name in mesh_stats
        },
    }


def _smoke_failed_validation(error_message: str) -> dict[str, Any]:
    lines = [line.strip() for line in error_message.splitlines() if line.strip()]
    reason_ids = _smoke_failure_reason_ids(error_message)
    return {
        "summary": "smoke_failed",
        "pass_lines": [],
        "warn_lines": [],
        "fail_lines": lines,
        "pass_checks": [],
        "warn_checks": [],
        "fail_checks": ["smoke_failed", *reason_ids],
        "reason_ids": reason_ids,
    }


def _preflight_failed_validation(error_message: str, reason_ids: list[str]) -> dict[str, Any]:
    lines = [line.strip() for line in error_message.splitlines() if line.strip()]
    return {
        "summary": "preflight_failed",
        "pass_lines": [],
        "warn_lines": [],
        "fail_lines": lines,
        "pass_checks": [],
        "warn_checks": [],
        "fail_checks": ["preflight_failed", *reason_ids],
        "reason_ids": list(reason_ids),
    }


def _surface_from_smoke_failure(spec_path: Path, failure: SmokeFailure) -> dict[str, Any]:
    return {
        "run_dir": str(failure.run_dir.resolve()) if failure.run_dir else None,
        "summary": {},
        "meta": {},
        "input_spec": _load_json(spec_path),
        "validation": _smoke_failed_validation(str(failure)),
        "runtime_stats": {},
        "smoke_error": str(failure),
    }


def _surface_from_preflight_failure(spec_path: Path, failure: PreflightFailure) -> dict[str, Any]:
    return {
        "run_dir": None,
        "summary": {},
        "meta": {},
        "input_spec": _load_json(spec_path),
        "validation": _preflight_failed_validation(
            str(failure),
            list(failure.summary.get("reason_ids", [])),
        ),
        "runtime_stats": {},
        "smoke_error": str(failure),
    }


def _strict_equiv_rows(baseline: dict[str, Any], runtime_bridge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_summary = baseline["summary"]
    runtime_summary = runtime_bridge["summary"]
    for path in STRICT_EQUIV_FIELDS:
        lhs = _nested_value(baseline_summary, path)
        rhs = _nested_value(runtime_summary, path)
        rows.append(
            {
                "field": ".".join(path),
                "baseline": lhs,
                "runtime_bridge": rhs,
                "match": lhs == rhs and lhs is not None and rhs is not None,
            }
        )
    return rows


def _trend_row_analysis(field: str,
                        lhs: Any,
                        rhs: Any,
                        delta: float | int | None) -> dict[str, Any]:
    guidance = TREND_EQUIV_FIELD_GUIDANCE.get(
        field,
        {
            "classification": "research_delta",
            "gate_level": "info",
            "policy": {
                "policy_id": "generic_research_surface",
                "enforcement": "informational",
                "expected_relation": "allow_divergence",
                "summary": "This trend field is currently treated as research-only and informational.",
            },
            "note": "This trend field is informational only and does not currently participate in PASS/FAIL.",
        },
    )
    delta_ratio = None
    if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)) and lhs != 0:
        delta_ratio = round((rhs - lhs) / lhs, 6)

    if lhs is None or rhs is None:
        return {
            "classification": "visibility_gap",
            "gate_level": guidance["gate_level"],
            "policy": dict(guidance["policy"]),
            "note": "One side does not currently export this trend field; it remains informational only and is not a PASS blocker.",
            "delta_ratio": None,
        }
    if delta == 0:
        return {
            "classification": "aligned",
            "gate_level": guidance["gate_level"],
            "policy": dict(guidance["policy"]),
            "note": "This research-level trend field is aligned for the current run; it remains informational only and is not a PASS blocker.",
            "delta_ratio": delta_ratio,
        }
    return {
        "classification": guidance["classification"],
        "gate_level": guidance["gate_level"],
        "policy": dict(guidance["policy"]),
        "note": guidance["note"],
        "delta_ratio": delta_ratio,
    }


def _trend_equiv_rows(baseline: dict[str, Any], runtime_bridge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_summary = baseline["summary"]
    runtime_summary = runtime_bridge["summary"]
    for path in TREND_EQUIV_FIELDS:
        lhs = _nested_value(baseline_summary, path)
        rhs = _nested_value(runtime_summary, path)
        delta = None
        if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
            delta = rhs - lhs
        field = ".".join(path)
        analysis = _trend_row_analysis(field, lhs, rhs, delta)
        rows.append(
            {
                "field": field,
                "baseline": lhs,
                "runtime_bridge": rhs,
                "delta": delta,
                "delta_ratio": analysis["delta_ratio"],
                "classification": analysis["classification"],
                "gate_level": analysis["gate_level"],
                "policy": analysis["policy"],
                "note": analysis["note"],
            }
        )
    return rows


def _trend_equiv_overview(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aligned = [row["field"] for row in rows if row.get("classification") == "aligned"]
    visibility_gap = [row["field"] for row in rows if row.get("classification") == "visibility_gap"]
    diverged = [
        row["field"]
        for row in rows
        if row.get("classification") not in {"aligned", "visibility_gap"}
    ]
    gate_warnings = [
        f"trend_visibility_gap:{row['field']}"
        for row in rows
        if row.get("gate_level") == "warn" and row.get("classification") == "visibility_gap"
    ]
    gate_failures = [
        f"trend_gate_failure:{row['field']}"
        for row in rows
        if row.get("gate_level") == "hard_fail" and row.get("classification") != "aligned"
    ]
    status = "failed" if gate_failures else ("passed_with_warning" if gate_warnings else "passed")
    policy_ids = _sorted_unique(
        [
            row.get("policy", {}).get("policy_id")
            for row in rows
            if row.get("policy", {}).get("policy_id")
        ]
    )
    return {
        "status": status,
        "gate_level": "info",
        "aligned_fields": aligned,
        "diverged_fields": diverged,
        "visibility_gap_fields": visibility_gap,
        "gate_warnings": gate_warnings,
        "gate_failures": gate_failures,
        "policy_ids": policy_ids,
        "summary_lines": [
            "Trend rows are informational only and do not currently participate in PASS/FAIL.",
            "Diverged fields capture high-level cost/accounting drift, while visibility_gap fields indicate missing export surface on one side.",
        ],
    }


def _runtime_bridge_gate(runtime_stats: dict[str, Any], *,
                         family: str = "external_dyn_desc_ref",
                         lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    stats = dict(runtime_stats or {})
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    check_catalog = _runtime_gate_check_catalog(lab_root=lab_root)
    reason_catalog = _runtime_gate_reason_catalog(lab_root=lab_root)
    fault_mode = str(family_policy.get("fault_mode", "quiescent"))
    timing_mode = str(family_policy.get("timing_mode", ""))
    queue_mode = str(family_policy.get("queue_mode", ""))
    visibility_only_progress = timing_mode == "wfi_barrier_completion_visibility"
    command_overdoorbell_overflow = queue_mode == "command_overdoorbell_overflow"
    completion_queue_overflow_after_visible_completion = (
        queue_mode == "completion_queue_overflow_after_visible_completion"
    )
    warnings: list[str] = []
    hard_failures: list[str] = []
    checks: list[dict[str, Any]] = []

    def _stat(name: str) -> float | None:
        value = stats.get(name)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _record(check_id: str,
                *,
                ok: bool,
                severity: str,
                actual: Any,
                expected: str,
                reason: str | None = None,
                note: str) -> None:
        if check_id not in check_catalog:
            raise KeyError(f"runtime gate check id missing from authority: {check_id}")
        if reason is not None and reason not in reason_catalog:
            raise KeyError(f"runtime gate reason id missing from authority: {reason}")
        summary = "passed" if ok else ("failed" if severity == "hard_fail" else "warning")
        checks.append(
            {
                "check": check_id,
                "check_id": check_id,
                "summary": summary,
                "severity": severity,
                "actual": actual,
                "expected": expected,
                "reason": reason,
                "reason_id": reason,
                "note": note,
                "contract": dict(check_catalog[check_id]),
                "reason_contract": dict(reason_catalog[reason]) if reason is not None else None,
            }
        )
        if ok or reason is None:
            return
        if severity == "hard_fail":
            hard_failures.append(reason)
        else:
            warnings.append(reason)

    provider_bound = _stat("riscv_snn_backend_runtime_bridge_provider_bound")
    _record(
        "provider_bound_visible",
        ok=provider_bound is not None and provider_bound > 0,
        severity="hard_fail",
        actual=provider_bound,
        expected="> 0",
        reason="runtime_bridge_provider_unbound",
        note="runtime_bridge should prove that the shadow provider bound successfully before this run can be treated as a strong PASS.",
    )

    completion_visible = _stat("riscv_snn_completion_visible_count")
    fault_count = _stat("riscv_snn_fault_count")
    accepted_fault_completion_progress = (
        fault_mode == "accepted_fault_required" and
        fault_count is not None and fault_count > 0 and (
            (completion_visible is not None and completion_visible > 0) or
            command_overdoorbell_overflow
        )
    )

    fused_step_count = _stat("riscv_snn_fused_step_completion_count")
    _record(
        "fused_step_completion_visible",
        ok=(
            (fused_step_count is not None and fused_step_count > 0) or
            accepted_fault_completion_progress or
            (visibility_only_progress and completion_visible is not None and completion_visible > 0)
        ),
        severity="warning",
        actual=fused_step_count,
        expected=(
            "> 0 or accepted-fault completion progress or completion-visible barrier wakeup"
            if visibility_only_progress
            else "> 0 or accepted-fault completion progress"
        ),
        reason="runtime_bridge_fused_step_completion_missing",
        note=(
            "Completion of at least one fused step is the minimum runtime_bridge forward-progress signal, "
            "unless this family intentionally retires through accepted-fault completions or through "
            "barrier-visible completion ordering."
        ),
    )

    _record(
        "completion_visible",
        ok=command_overdoorbell_overflow or (completion_visible is not None and completion_visible > 0),
        severity="warning",
        actual=completion_visible,
        expected="> 0 or command-overdoorbell overflow family",
        reason=None if command_overdoorbell_overflow else "runtime_bridge_completion_visibility_missing",
        note=(
            "Software-visible completions should normally be present before the run is treated as a strong PASS. "
            "The command-overdoorbell queue overflow family is allowed to wake on fault before any completion becomes visible."
        ),
    )

    completion_consumed = _stat("riscv_snn_completion_consumed_count")
    _record(
        "completion_consumed_covers_visible",
        ok=(completion_visible is None or completion_visible <= 0) or (
            accepted_fault_completion_progress or
            visibility_only_progress or
            command_overdoorbell_overflow or
            completion_queue_overflow_after_visible_completion or
            (completion_consumed is not None and completion_consumed >= completion_visible)
        ),
        severity="warning",
        actual=completion_consumed,
        expected=(
                "queue-overdoorbell family may halt before software completion ack"
                if command_overdoorbell_overflow
                else (
                "accepted-fault family may halt before software completion ack"
                if accepted_fault_completion_progress
                else (
                "completion-overflow family may hold the first visible completion unacked"
                if completion_queue_overflow_after_visible_completion
                else (
                "visibility-only barrier family may defer completion consumption"
                if visibility_only_progress
                else (
                    f">= completion_visible ({completion_visible})"
                    if completion_visible is not None
                    else ">= completion_visible"
                )
                )
                )
                )
        ),
        reason=(
            None
            if (
                accepted_fault_completion_progress
                or command_overdoorbell_overflow
                or completion_queue_overflow_after_visible_completion
            )
            else "runtime_bridge_completion_not_fully_consumed"
        ),
        note=(
            "When completions are visible, the firmware path should consume them as well, "
            "unless this family is explicitly freezing completion visibility before software consumption "
            "or faulting before completion ack becomes part of the contract."
        ),
    )

    last_fault_csr = _stat("riscv_snn_last_fault_csr")
    if fault_mode == "accepted_fault_required":
        _record(
            "fault_observed",
            ok=fault_count is not None and fault_count > 0,
            severity="hard_fail",
            actual=fault_count,
            expected="> 0",
            reason="runtime_bridge_expected_fault_missing",
            note="This equivalence family expects an accepted fault to reach the architectural runtime surface.",
        )
    if command_overdoorbell_overflow:
        expected_single_fault_snapshot = 0x0000000100000210
        expected_fault_snapshot_total = int(fault_count or 0) * expected_single_fault_snapshot
        _record(
            "queue_fault_signature",
            ok=(
                fault_count is not None and fault_count > 0 and
                int(last_fault_csr or 0) == expected_fault_snapshot_total
            ),
            severity="hard_fail",
            actual={
                "fault_count": fault_count,
                "last_fault_csr": int(last_fault_csr or 0),
                "expected_fault_snapshot_total": expected_fault_snapshot_total,
            },
            expected="last_fault_csr == fault_count * 0x0000000100000210",
            reason="runtime_bridge_queue_fault_signature_mismatch",
            note="The queue backpressure reference freezes a command-queue overflow fault sourced from a one-entry visible queue.",
        )
    if completion_queue_overflow_after_visible_completion:
        expected_single_fault_snapshot = 0x0000000100000211
        expected_fault_snapshot_total = int(fault_count or 0) * expected_single_fault_snapshot
        _record(
            "completion_queue_fault_signature",
            ok=(
                fault_count is not None and fault_count > 0 and
                int(last_fault_csr or 0) == expected_fault_snapshot_total
            ),
            severity="hard_fail",
            actual={
                "fault_count": fault_count,
                "last_fault_csr": int(last_fault_csr or 0),
                "expected_fault_snapshot_total": expected_fault_snapshot_total,
            },
            expected="last_fault_csr == fault_count * 0x0000000100000211",
            reason="runtime_bridge_completion_queue_fault_signature_mismatch",
            note="The completion queue overflow reference freezes a cmpq-full fault after exactly one software-visible completion remains unacked.",
        )
    _record(
        "fault_snapshot_consistent",
        ok=(fault_count is None or fault_count <= 0) or (last_fault_csr is not None and last_fault_csr > 0),
        severity="hard_fail",
        actual={"fault_count": fault_count, "last_fault_csr": last_fault_csr},
        expected="fault_count == 0 or last_fault_csr > 0",
        reason="runtime_bridge_fault_snapshot_missing",
        note="If faults occurred, the last fault CSR snapshot must remain architecturally visible.",
    )
    if fault_mode == "quiescent":
        _record(
            "fault_snapshot_quiescent",
            ok=(fault_count is None or fault_count > 0) or (last_fault_csr in (None, 0, 0.0)),
            severity="warning",
            actual={"fault_count": fault_count, "last_fault_csr": last_fault_csr},
            expected="fault_count == 0 implies last_fault_csr == 0",
            reason="runtime_bridge_fault_snapshot_stale",
            note="A quiescent run should not carry a stale non-zero last fault CSR snapshot.",
        )

    last_completion_status = _stat("riscv_snn_last_completion_status")
    if fault_mode == "quiescent" and not visibility_only_progress:
        _record(
            "last_completion_status_clean",
            ok=last_completion_status in (None, 0, 0.0),
            severity="warning",
            actual=last_completion_status,
            expected="0",
            reason="runtime_bridge_last_completion_nonzero",
            note="The success reference path is expected to retire with completion status 0.",
        )

    if hard_failures:
        summary = "failed"
    elif warnings:
        summary = "passed_with_warning"
    else:
        summary = "passed"
    return {
        "summary": summary,
        "ok": not hard_failures,
        "family": family,
        "policy": family_policy,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "checks": checks,
    }


def _run_equivalence_from_specs(family: str,
                                *,
                                baseline_spec: Path,
                                runtime_bridge_spec: Path,
                                summary_path: Path | None = None,
                                summary_metadata: dict[str, Any] | None = None,
                                lab_root: Path = LAB_ROOT,
                                runner: Runner = run_command) -> dict[str, Any]:
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    if not baseline_spec.exists():
        raise FileNotFoundError(f"missing equivalence baseline spec: {baseline_spec}")
    if not runtime_bridge_spec.exists():
        raise FileNotFoundError(f"missing runtime bridge spec: {runtime_bridge_spec}")
    runtime_bridge_build_preflight = runtime_bridge_build_guard(
        spec_path=runtime_bridge_spec,
        lab_root=lab_root,
    )
    runtime_bridge_build_preflight_rollup = _build_preflight_rollup(runtime_bridge_build_preflight)

    baseline_preflight_failure: PreflightFailure | None = None
    runtime_bridge_preflight_failure: PreflightFailure | None = None
    baseline_smoke_failure: SmokeFailure | None = None
    runtime_bridge_smoke_failure: SmokeFailure | None = None
    try:
        baseline_run_dir, baseline_smoke = _run_smoke_with_optional_failure(
            spec_path=baseline_spec,
            lab_root=lab_root,
            runner=runner,
            allow_failed_run=True,
        )
        baseline_surface = _surface_from_run_dir(baseline_run_dir)
        baseline_surface["smoke_error"] = None
    except PreflightFailure as exc:
        baseline_preflight_failure = exc
        baseline_smoke = exc.proc
        baseline_surface = _surface_from_preflight_failure(baseline_spec, exc)
    except SmokeFailure as exc:
        baseline_smoke_failure = exc
        baseline_smoke = exc.proc
        baseline_surface = _surface_from_smoke_failure(baseline_spec, exc)

    try:
        runtime_bridge_run_dir, runtime_bridge_smoke = _run_smoke_with_optional_failure(
            spec_path=runtime_bridge_spec,
            lab_root=lab_root,
            runner=runner,
            allow_failed_run=True,
        )
        runtime_bridge_surface = _surface_from_run_dir(runtime_bridge_run_dir)
        runtime_bridge_surface["smoke_error"] = None
    except PreflightFailure as exc:
        runtime_bridge_preflight_failure = exc
        runtime_bridge_smoke = exc.proc
        runtime_bridge_surface = _surface_from_preflight_failure(runtime_bridge_spec, exc)
    except SmokeFailure as exc:
        runtime_bridge_smoke_failure = exc
        runtime_bridge_smoke = exc.proc
        runtime_bridge_surface = _surface_from_smoke_failure(runtime_bridge_spec, exc)
    baseline_equiv_validation = _equiv_validation_summary(
        family,
        "snn_baseline",
        baseline_surface["validation"],
    )
    runtime_bridge_equiv_validation = _equiv_validation_summary(
        family,
        "runtime_bridge",
        runtime_bridge_surface["validation"],
    )

    execution_failures_present = (
        baseline_preflight_failure is not None
        or runtime_bridge_preflight_failure is not None
        or baseline_smoke_failure is not None
        or runtime_bridge_smoke_failure is not None
    )
    strict_rows = [] if execution_failures_present else _strict_equiv_rows(baseline_surface, runtime_bridge_surface)
    trend_rows = [] if execution_failures_present else _trend_equiv_rows(baseline_surface, runtime_bridge_surface)
    trend_overview = _trend_equiv_overview(trend_rows) if trend_rows else {
        "status": "passed",
        "gate_level": "info",
        "aligned_fields": [],
        "diverged_fields": [],
        "visibility_gap_fields": [],
        "gate_warnings": [],
        "gate_failures": [],
        "policy_ids": [],
        "summary_lines": [],
    }
    validation_ok = (
        baseline_equiv_validation["ok"] and
        runtime_bridge_equiv_validation["ok"]
    )
    strict_ok = all(row["match"] for row in strict_rows)
    runtime_bridge_gate = _runtime_bridge_gate(
        runtime_bridge_surface["runtime_stats"],
        family=family,
        lab_root=lab_root,
    ) if runtime_bridge_preflight_failure is None and runtime_bridge_smoke_failure is None else {
        "summary": "not_run",
        "ok": False,
        "family": family,
        "policy": family_policy,
        "hard_failures": [],
        "warnings": [],
        "checks": [],
    }
    gate_reasons: list[str] = []
    if baseline_preflight_failure is not None:
        gate_reasons.append("baseline_preflight_failed")
        gate_reasons.extend(
            f"baseline_{reason}"
            for reason in baseline_surface["validation"].get("reason_ids", [])
        )
    if runtime_bridge_preflight_failure is not None:
        gate_reasons.append("runtime_bridge_preflight_failed")
        gate_reasons.extend(
            f"runtime_bridge_{reason}"
            for reason in runtime_bridge_surface["validation"].get("reason_ids", [])
        )
    if baseline_smoke_failure is not None:
        gate_reasons.append("baseline_smoke_failed")
        gate_reasons.extend(
            f"baseline_{reason}"
            for reason in baseline_surface["validation"].get("reason_ids", [])
        )
    if runtime_bridge_smoke_failure is not None:
        gate_reasons.append("runtime_bridge_smoke_failed")
        gate_reasons.extend(
            f"runtime_bridge_{reason}"
            for reason in runtime_bridge_surface["validation"].get("reason_ids", [])
        )
    if not execution_failures_present:
        if not baseline_equiv_validation["ok"]:
            gate_reasons.append("baseline_validation_failed")
        if not runtime_bridge_equiv_validation["ok"]:
            gate_reasons.append("runtime_bridge_validation_failed")
        if not strict_ok:
            gate_reasons.extend(
                f"strict_mismatch:{row['field']}"
                for row in strict_rows
                if not row["match"]
            )
        gate_reasons.extend(trend_overview["gate_failures"])
        gate_reasons.extend(trend_overview["gate_warnings"])
        gate_reasons.extend(runtime_bridge_gate["hard_failures"])
        gate_reasons.extend(runtime_bridge_gate["warnings"])
    if (
        execution_failures_present
        or not validation_ok
        or not strict_ok
        or trend_overview["status"] == "failed"
        or runtime_bridge_gate["summary"] == "failed"
    ):
        status = "FAIL"
    elif trend_overview["status"] == "passed_with_warning" or runtime_bridge_gate["summary"] == "passed_with_warning":
        status = "WARN"
    else:
        status = "PASS"

    resolved_summary_path = summary_path or default_equiv_summary_path(family, lab_root=lab_root)
    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "family": family,
        "family_policy": family_policy,
        "status": status,
        "gate_reasons": gate_reasons,
        "baseline": {
            "role": "snn_baseline",
            "spec_path": str(baseline_spec),
            "run_dir": baseline_surface["run_dir"],
            "smoke_returncode": baseline_smoke.returncode,
            "smoke_error": baseline_surface["smoke_error"],
            "validation": baseline_surface["validation"]["summary"],
            "validation_detail": baseline_surface["validation"],
            "equiv_validation": baseline_equiv_validation,
            "workload_impl": baseline_surface["input_spec"].get("workload", {}).get("impl"),
        },
        "runtime_bridge": {
            "role": "runtime_bridge",
            "spec_path": str(runtime_bridge_spec),
            "run_dir": runtime_bridge_surface["run_dir"],
            "smoke_returncode": runtime_bridge_smoke.returncode,
            "smoke_error": runtime_bridge_surface["smoke_error"],
            "validation": runtime_bridge_surface["validation"]["summary"],
            "validation_detail": runtime_bridge_surface["validation"],
            "equiv_validation": runtime_bridge_equiv_validation,
            "workload_impl": runtime_bridge_surface["input_spec"].get("workload", {}).get("impl"),
            "runtime_stats": runtime_bridge_surface["runtime_stats"],
            "runtime_gate": runtime_bridge_gate,
            "build_preflight": runtime_bridge_build_preflight,
            "build_preflight_rollup": runtime_bridge_build_preflight_rollup,
        },
        "compare": {
            "strict": strict_rows,
            "trend": trend_rows,
            "trend_overview": trend_overview,
        },
    }
    if summary_metadata:
        summary.update(summary_metadata)
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def _run_equivalence_with_spec_paths(family: str,
                                     *,
                                     baseline_spec: Path,
                                     runtime_bridge_spec: Path,
                                     summary_path: Path | None = None,
                                     summary_metadata: dict[str, Any] | None = None,
                                     lab_root: Path = LAB_ROOT,
                                     runner: Runner = run_command) -> dict[str, Any]:
    return _run_equivalence_from_specs(
        family,
        baseline_spec=baseline_spec,
        runtime_bridge_spec=runtime_bridge_spec,
        summary_path=summary_path,
        summary_metadata=summary_metadata,
        lab_root=lab_root,
        runner=runner,
    )


def run_equivalence(family: str,
                    *,
                    summary_path: Path | None = None,
                    lab_root: Path = LAB_ROOT,
                    runner: Runner = run_command) -> dict[str, Any]:
    try:
        family_specs = EQUIV_FAMILY_SPECS[family]
    except KeyError as exc:
        raise ValueError(f"unknown equivalence family: {family}") from exc

    baseline_spec = lab_root / "specs" / family_specs["snn_baseline"]
    runtime_bridge_spec = lab_root / "specs" / family_specs["runtime_bridge"]
    return _run_equivalence_from_specs(
        family,
        baseline_spec=baseline_spec,
        runtime_bridge_spec=runtime_bridge_spec,
        summary_path=summary_path,
        lab_root=lab_root,
        runner=runner,
    )


def _resolve_equiv_families(families: list[str] | None,
                            *,
                            group: str = "all",
                            lab_root: Path = LAB_ROOT) -> list[str]:
    if families is None:
        return _canonical_equiv_families(group, lab_root=lab_root)

    resolved: list[str] = []
    seen: set[str] = set()
    for family in families:
        if family not in EQUIV_FAMILY_SPECS:
            raise ValueError(f"unknown equivalence family: {family}")
        if family in seen:
            continue
        seen.add(family)
        resolved.append(family)
    return resolved


def _resolve_reference_program_compare_families(
    families: list[str] | None,
    *,
    group: str = "all",
    lab_root: Path = LAB_ROOT,
) -> list[str]:
    known_families = set(_reference_program_compare_family_names(lab_root=lab_root))
    if families is None:
        if group == "all":
            return list(_reference_program_compare_family_names(lab_root=lab_root))
        return _canonical_equiv_families(group, lab_root=lab_root)

    resolved: list[str] = []
    seen: set[str] = set()
    for family in families:
        if family not in known_families:
            raise ValueError(f"unknown reference program compare family: {family}")
        if family in seen:
            continue
        seen.add(family)
        resolved.append(family)
    return resolved


def run_equiv_matrix(families: list[str] | None = None,
                     *,
                     group: str = "all",
                     lab_root: Path = LAB_ROOT,
                     runner: Runner = run_command,
                     summary_path: Path | None = None) -> dict[str, Any]:
    resolved_families = _resolve_equiv_families(families, group=group, lab_root=lab_root)
    canonical_surface = _is_canonical_equiv_surface(group, resolved_families, lab_root=lab_root)
    family_rows: list[dict[str, Any]] = []
    for family in resolved_families:
        family_summary = run_equivalence(
            family,
            lab_root=lab_root,
            runner=runner,
        )
        family_rows.append(
            {
                "family": family_summary["family"],
                "status": family_summary["status"],
                "summary_path": family_summary["summary_path"],
                "gate_reasons": list(family_summary.get("gate_reasons", [])),
                "runtime_bridge_build_preflight_rollup": dict(
                    family_summary.get("runtime_bridge", {}).get("build_preflight_rollup") or {}
                ),
            }
        )

    if summary_path is not None:
        resolved_summary_path = summary_path
    else:
        resolved_summary_path = _default_equiv_matrix_summary_path(
            group,
            resolved_families,
            lab_root=lab_root,
        )
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_DATED_EQUIV_MATRIX,
            scope="family_level_equivalence_authority",
            producer="riscv_snn_lab.run_equiv_matrix",
        ),
        "gate_name": "riscv_snn_equiv_matrix",
        "canonical_surface": canonical_surface,
        "requested_group": group,
        "count": len(family_rows),
        "all_ok": all(row["status"] == "PASS" for row in family_rows),
        "requested_families": resolved_families,
        "families": family_rows,
        "runtime_bridge_build_preflight_rollup": _matrix_build_preflight_rollup(family_rows),
    }
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def _family_asset_audit_families(*,
                                 family: str | None = None,
                                 lab_root: Path = LAB_ROOT) -> list[str]:
    runtime_gate_families = list(_runtime_gate_family_policies(lab_root=lab_root).keys())
    known_families = _sorted_unique([*runtime_gate_families, *EQUIV_FAMILY_SPECS.keys()])
    if family is None:
        return known_families
    if family not in known_families:
        raise ValueError(f"unknown family asset audit target: {family}")
    return [family]


def _builder_sample_program_names(*, runner: Runner = run_command) -> set[str]:
    manifest = _load_program_manifest(runner=runner)
    return {
        str(name)
        for name in dict(manifest.get("samples", {}) or {}).keys()
    }


def _toolchain_asset_state(program: str, *, lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    toolchain_dir = toolchain_source_dir(program, lab_root=lab_root)
    required_files = ("Makefile", "main.S", "abi.inc")
    missing_files = [
        name
        for name in required_files
        if not (toolchain_dir / name).exists()
    ]
    return {
        "program": program,
        "path": str(toolchain_dir),
        "exists": toolchain_dir.exists(),
        "required_files": list(required_files),
        "missing_files": missing_files,
    }


def audit_family_assets(*,
                        family: str | None = None,
                        families: list[str] | None = None,
                        output_path: Path | None = None,
                        lab_root: Path = LAB_ROOT,
                        runner: Runner = run_command) -> dict[str, Any]:
    if family is not None and families is not None:
        raise ValueError("family-asset-audit accepts either family or families, not both")
    builder_sample_names = _builder_sample_program_names(runner=runner)
    runtime_gate_families = set(_runtime_gate_family_policies(lab_root=lab_root).keys())
    if families is not None:
        resolved_families = _resolve_equiv_families(list(families), lab_root=lab_root)
    else:
        resolved_families = _family_asset_audit_families(family=family, lab_root=lab_root)
    family_rows: list[dict[str, Any]] = []
    for resolved_family in resolved_families:
        issues: list[str] = []
        family_specs = EQUIV_FAMILY_SPECS.get(resolved_family)
        runtime_gate_authority_present = resolved_family in runtime_gate_families
        if not runtime_gate_authority_present:
            issues.append("runtime_gate_family_missing")
        if family_specs is None:
            issues.append("equiv_spec_mapping_missing")
            baseline_spec_path = None
            runtime_bridge_spec_path = None
            baseline_spec_exists = False
            runtime_bridge_spec_exists = False
            baseline_impl = None
            runtime_bridge_impl = None
            backend_name = None
            firmware_elf_path = None
            firmware_elf_exists = False
            uses_toolchain_bridge = False
            toolchain_source = {
                "program": None,
                "path": None,
                "exists": False,
                "required_files": [],
                "missing_files": [],
            }
        else:
            baseline_spec_path = lab_root / "specs" / family_specs["snn_baseline"]
            runtime_bridge_spec_path = lab_root / "specs" / family_specs["runtime_bridge"]
            baseline_spec_exists = baseline_spec_path.exists()
            runtime_bridge_spec_exists = runtime_bridge_spec_path.exists()

            baseline_impl = None
            runtime_bridge_impl = None
            backend_name = None
            firmware_elf_path = None
            firmware_elf_exists = False
            uses_toolchain_bridge = False
            toolchain_source = {
                "program": None,
                "path": None,
                "exists": False,
                "required_files": [],
                "missing_files": [],
            }

            if not baseline_spec_exists:
                issues.append("baseline_spec_missing")
            else:
                baseline_payload = _load_json(baseline_spec_path)
                baseline_impl = _nested_value(baseline_payload, ("workload", "impl"))
                if baseline_impl != "snn":
                    issues.append("baseline_impl_not_snn")

            if not runtime_bridge_spec_exists:
                issues.append("runtime_bridge_spec_missing")
            else:
                runtime_bridge_payload = _load_json(runtime_bridge_spec_path)
                runtime_bridge_impl = _nested_value(runtime_bridge_payload, ("workload", "impl"))
                backend_name = _nested_value(runtime_bridge_payload, ("workload", "params", "backend_name"))
                firmware_elf_raw = _nested_value(runtime_bridge_payload, ("workload", "params", "firmware_elf"))
                if runtime_bridge_impl != "riscv_snn":
                    issues.append("runtime_bridge_impl_not_riscv_snn")
                if backend_name != "runtime_bridge":
                    issues.append("runtime_bridge_backend_name_mismatch")
                if not isinstance(firmware_elf_raw, str) or not firmware_elf_raw.strip():
                    issues.append("runtime_bridge_firmware_elf_missing")
                else:
                    firmware_elf_path = Path(firmware_elf_raw)
                    firmware_elf_exists = firmware_elf_path.exists()
                    uses_toolchain_bridge = firmware_elf_path.stem.endswith("_toolchain")
                    if uses_toolchain_bridge:
                        toolchain_source = _toolchain_asset_state(firmware_elf_path.stem, lab_root=lab_root)
                        if not toolchain_source["exists"]:
                            issues.append("toolchain_source_missing")
                        if toolchain_source["missing_files"]:
                            issues.append("toolchain_source_incomplete")

        builder_sample_exists = resolved_family in builder_sample_names
        if not builder_sample_exists:
            issues.append("builder_sample_missing")

        baseline_spec_ok = baseline_spec_exists and baseline_impl == "snn"
        runtime_bridge_spec_ok = (
            runtime_bridge_spec_exists
            and runtime_bridge_impl == "riscv_snn"
            and backend_name == "runtime_bridge"
            and firmware_elf_path is not None
        )
        toolchain_assets_ok = (
            not uses_toolchain_bridge
            or (
                bool(toolchain_source["exists"])
                and not toolchain_source["missing_files"]
            )
        )
        row = {
            "family": resolved_family,
            "runtime_gate_authority_present": runtime_gate_authority_present,
            "builder_sample_exists": builder_sample_exists,
            "builder_sample_present": builder_sample_exists,
            "builder_program": resolved_family,
            "equiv_spec_mapping_present": family_specs is not None,
            "baseline_spec_path": str(baseline_spec_path) if baseline_spec_path is not None else None,
            "baseline_spec_exists": baseline_spec_exists,
            "baseline_impl": baseline_impl,
            "baseline_spec_ok": baseline_spec_ok,
            "runtime_bridge_spec_path": (
                str(runtime_bridge_spec_path) if runtime_bridge_spec_path is not None else None
            ),
            "runtime_bridge_spec_exists": runtime_bridge_spec_exists,
            "runtime_bridge_impl": runtime_bridge_impl,
            "runtime_bridge_backend_name": backend_name,
            "runtime_bridge_spec_ok": runtime_bridge_spec_ok,
            "runtime_bridge_firmware_elf": str(firmware_elf_path) if firmware_elf_path is not None else None,
            "runtime_bridge_firmware_elf_exists": firmware_elf_exists,
            "uses_toolchain_bridge": uses_toolchain_bridge,
            "toolchain_program": toolchain_source["program"],
            "toolchain_source_path": toolchain_source["path"],
            "toolchain_source_exists": bool(toolchain_source["exists"]),
            "toolchain_missing_files": list(toolchain_source["missing_files"]),
            "toolchain_assets_ok": toolchain_assets_ok,
            "issues": issues,
            "all_ok": not issues,
        }
        family_rows.append(row)

    resolved_output_path = output_path or default_reference_path(
        (
            "family-asset-audit"
            if family is None
            else f"{family.replace('_', '-')}-family-asset-audit"
        ),
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_DATED_FAMILY_ASSET_AUDIT,
            scope="family_asset_consistency_observer",
            producer="riscv_snn_lab.audit_family_assets",
        ),
        "family": family,
        "count": len(family_rows),
        "builder_sample_count": len(builder_sample_names),
        "families": family_rows,
        "all_ok": all(row["all_ok"] for row in family_rows),
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, summary)
    return summary


def _family_lane_overrides(*,
                           sim_time: str | None = None,
                           mesh_size: int | None = None,
                           hart_isa: str | None = None,
                           local_mem_bytes: int | None = None,
                           cmd_queue_entries: int | None = None,
                           cmp_queue_entries: int | None = None,
                           rx_debug_queue_entries: int | None = None,
                           boot_addr: int | None = None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if sim_time is not None:
        overrides["sim_time"] = str(sim_time)
    if mesh_size is not None:
        overrides["mesh_size"] = int(mesh_size)
    if hart_isa is not None:
        overrides["hart_isa"] = str(hart_isa)
    if local_mem_bytes is not None:
        overrides["local_mem_bytes"] = int(local_mem_bytes)
    if cmd_queue_entries is not None:
        overrides["cmd_queue_entries"] = int(cmd_queue_entries)
    if cmp_queue_entries is not None:
        overrides["cmp_queue_entries"] = int(cmp_queue_entries)
    if rx_debug_queue_entries is not None:
        overrides["rx_debug_queue_entries"] = int(rx_debug_queue_entries)
    if boot_addr is not None:
        overrides["boot_addr"] = int(boot_addr)
    return overrides


def _family_lane_paths(family: str,
                       overrides: dict[str, Any],
                       *,
                       lab_root: Path = LAB_ROOT,
                       lane_root: Path | None = None) -> tuple[str, Path, Path, Path]:
    lane_id = _surface_digest({"family": family, "overrides": overrides})
    resolved_lane_root = lane_root or (lab_root / "family_lanes" / family / lane_id)
    baseline_spec_path = resolved_lane_root / f"{family}_snn_baseline.json"
    runtime_bridge_spec_path = resolved_lane_root / f"{family}_runtime_bridge.json"
    return lane_id, resolved_lane_root, baseline_spec_path, runtime_bridge_spec_path


def _apply_family_lane_overrides(*,
                                 baseline_payload: dict[str, Any],
                                 runtime_bridge_payload: dict[str, Any],
                                 overrides: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_variant = json.loads(json.dumps(baseline_payload))
    runtime_bridge_variant = json.loads(json.dumps(runtime_bridge_payload))

    if "mesh_size" in overrides:
        for payload in (baseline_variant, runtime_bridge_variant):
            payload.setdefault("platform", {})
            payload["platform"]["mesh_size"] = int(overrides["mesh_size"])
    if "sim_time" in overrides:
        for payload in (baseline_variant, runtime_bridge_variant):
            payload.setdefault("platform", {})
            payload["platform"].setdefault("stop", {})
            payload["platform"]["stop"]["simulation_time"] = str(overrides["sim_time"])
    if any(key in overrides for key in FAMILY_LANE_RUNTIME_PARAM_FIELDS):
        runtime_bridge_variant.setdefault("workload", {})
        runtime_bridge_variant["workload"].setdefault("params", {})
        for key in FAMILY_LANE_RUNTIME_PARAM_FIELDS:
            if key in overrides:
                runtime_bridge_variant["workload"]["params"][key] = overrides[key]
    return baseline_variant, runtime_bridge_variant


def _resolve_family_lane_matrix_families(families: list[str] | None,
                                         *,
                                         lab_root: Path = LAB_ROOT) -> list[str]:
    if not families:
        raise ValueError("family-lane-matrix requires at least one --family")
    return _resolve_equiv_families(list(families), group="all", lab_root=lab_root)


def _default_family_lane_preset_summary_path(preset: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return default_reference_path(
        f"family-lane-preset-{preset.replace('_', '-')}",
        lab_root=lab_root,
    )


def _default_family_lane_matrix_preset_summary_path(preset: str, *, lab_root: Path = LAB_ROOT) -> Path:
    return default_reference_path(
        f"family-lane-matrix-preset-{preset.replace('_', '-')}",
        lab_root=lab_root,
    )


def _family_lane_override_kwargs(overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "sim_time": overrides.get("sim_time"),
        "mesh_size": overrides.get("mesh_size"),
        "hart_isa": overrides.get("hart_isa"),
        "local_mem_bytes": overrides.get("local_mem_bytes"),
        "cmd_queue_entries": overrides.get("cmd_queue_entries"),
        "cmp_queue_entries": overrides.get("cmp_queue_entries"),
        "rx_debug_queue_entries": overrides.get("rx_debug_queue_entries"),
        "boot_addr": overrides.get("boot_addr"),
    }


def _attach_family_lane_preset_metadata(summary: dict[str, Any],
                                        *,
                                        preset_name: str,
                                        preset_payload: dict[str, Any]) -> dict[str, Any]:
    enriched = json.loads(json.dumps(summary))
    enriched["preset"] = preset_name
    enriched["preset_name"] = preset_name
    enriched["preset_description"] = str(preset_payload.get("description", ""))
    enriched["preset_research_surface_role"] = str(preset_payload.get("research_surface_role", "unknown"))
    enriched["preset_included_in_stable_authority"] = bool(
        preset_payload.get("included_in_stable_authority", False)
    )
    if "family" in preset_payload:
        enriched["preset_family"] = str(preset_payload["family"])
    if "families" in preset_payload:
        enriched["preset_families"] = list(preset_payload["families"])
    if "overrides" in preset_payload:
        enriched["preset_overrides"] = dict(preset_payload["overrides"])
    summary_path = enriched.get("summary_path")
    if isinstance(summary_path, str) and summary_path:
        _write_json(Path(summary_path), enriched)
    return enriched


def run_family_lane(family: str | None = None,
                    *,
                    preset: str | None = None,
                    sim_time: str | None = None,
                    mesh_size: int | None = None,
                    hart_isa: str | None = None,
                    local_mem_bytes: int | None = None,
                    cmd_queue_entries: int | None = None,
                    cmp_queue_entries: int | None = None,
                    rx_debug_queue_entries: int | None = None,
                    boot_addr: int | None = None,
                    lane_root: Path | None = None,
                    summary_path: Path | None = None,
                    lab_root: Path = LAB_ROOT,
                    runner: Runner = run_command) -> dict[str, Any]:
    preset_payload: dict[str, Any] | None = None
    resolved_family = family
    explicit_overrides = _family_lane_overrides(
        sim_time=sim_time,
        mesh_size=mesh_size,
        hart_isa=hart_isa,
        local_mem_bytes=local_mem_bytes,
        cmd_queue_entries=cmd_queue_entries,
        cmp_queue_entries=cmp_queue_entries,
        rx_debug_queue_entries=rx_debug_queue_entries,
        boot_addr=boot_addr,
    )
    if preset is not None:
        preset_payload = _resolve_family_lane_preset(preset, mode="lane")
        if family is not None:
            raise ValueError("family-lane preset cannot be combined with explicit --family")
        if explicit_overrides:
            raise ValueError("family-lane preset cannot be combined with explicit overrides")
        resolved_family = str(preset_payload["family"])
    if resolved_family is None:
        raise ValueError("family-lane requires either --family semantics or a preset")
    try:
        family_specs = EQUIV_FAMILY_SPECS[resolved_family]
    except KeyError as exc:
        raise ValueError(f"unknown equivalence family: {resolved_family}") from exc

    overrides = dict((preset_payload or {}).get("overrides") or {})
    overrides.update(explicit_overrides)
    if not overrides:
        raise ValueError("family-lane requires at least one override")

    template_baseline_spec = lab_root / "specs" / family_specs["snn_baseline"]
    template_runtime_bridge_spec = lab_root / "specs" / family_specs["runtime_bridge"]
    if not template_baseline_spec.exists():
        raise FileNotFoundError(f"missing equivalence baseline spec: {template_baseline_spec}")
    if not template_runtime_bridge_spec.exists():
        raise FileNotFoundError(f"missing runtime bridge spec: {template_runtime_bridge_spec}")

    baseline_payload = _load_json(template_baseline_spec)
    runtime_bridge_payload = _load_json(template_runtime_bridge_spec)
    baseline_variant, runtime_bridge_variant = _apply_family_lane_overrides(
        baseline_payload=baseline_payload,
        runtime_bridge_payload=runtime_bridge_payload,
        overrides=overrides,
    )
    lane_id, resolved_lane_root, baseline_spec_path, runtime_bridge_spec_path = _family_lane_paths(
        resolved_family,
        overrides,
        lab_root=lab_root,
        lane_root=lane_root,
    )
    _write_json_text(baseline_spec_path, baseline_variant)
    _write_json_text(runtime_bridge_spec_path, runtime_bridge_variant)
    if preset is not None:
        resolved_summary_path = summary_path or _default_family_lane_preset_summary_path(
            preset,
            lab_root=lab_root,
        )
    else:
        resolved_summary_path = summary_path or default_reference_path(
            f"family-lane-{resolved_family.replace('_', '-')}-subset-{lane_id}",
            lab_root=lab_root,
        )
    preset_metadata = {}
    if preset is not None and preset_payload is not None:
        preset_metadata = {
            "preset": preset,
            "preset_name": preset,
            "preset_description": str(preset_payload.get("description", "")),
            "preset_research_surface_role": str(preset_payload.get("research_surface_role", "unknown")),
            "preset_included_in_stable_authority": bool(
                preset_payload.get("included_in_stable_authority", False)
            ),
        }
    summary = _run_equivalence_with_spec_paths(
        resolved_family,
        baseline_spec=baseline_spec_path,
        runtime_bridge_spec=runtime_bridge_spec_path,
        summary_path=resolved_summary_path,
        summary_metadata={
            "artifact_role": ARTIFACT_ROLE_DATED_FAMILY_LANE_EQUIVALENCE,
            "authority_scope": "research_subset_lane",
            "canonical_surface": False,
            "lane_id": lane_id,
            "lane_root": str(resolved_lane_root),
            "lane_overrides": overrides,
            "template_specs": {
                "snn_baseline": str(template_baseline_spec),
                "runtime_bridge": str(template_runtime_bridge_spec),
            },
            "variant_specs": {
                "snn_baseline": str(baseline_spec_path),
                "runtime_bridge": str(runtime_bridge_spec_path),
            },
            **preset_metadata,
        },
        lab_root=lab_root,
        runner=runner,
    )
    summary.setdefault("canonical_surface", False)
    summary["family"] = resolved_family
    summary["lane_id"] = lane_id
    summary["lane_root"] = str(resolved_lane_root)
    summary["overrides"] = dict(overrides)
    summary["lane_overrides"] = dict(overrides)
    summary["baseline_spec_path"] = str(baseline_spec_path)
    summary["runtime_bridge_spec_path"] = str(runtime_bridge_spec_path)
    summary["equivalence_summary_path"] = str(summary.get("summary_path", resolved_summary_path))
    if preset is not None and preset_payload is not None:
        summary["preset"] = preset
        summary["preset_name"] = preset
        summary["preset_description"] = str(preset_payload.get("description", ""))
        summary["preset_research_surface_role"] = str(preset_payload.get("research_surface_role", "unknown"))
        summary["preset_included_in_stable_authority"] = bool(
            preset_payload.get("included_in_stable_authority", False)
        )
    return summary


def run_family_lane_preset(preset: str,
                           *,
                           sim_time: str | None = None,
                           mesh_size: int | None = None,
                           hart_isa: str | None = None,
                           local_mem_bytes: int | None = None,
                           cmd_queue_entries: int | None = None,
                           cmp_queue_entries: int | None = None,
                           rx_debug_queue_entries: int | None = None,
                           boot_addr: int | None = None,
                           summary_path: Path | None = None,
                           lab_root: Path = LAB_ROOT,
                           runner: Runner = run_command) -> dict[str, Any]:
    explicit_overrides = _family_lane_overrides(
        sim_time=sim_time,
        mesh_size=mesh_size,
        hart_isa=hart_isa,
        local_mem_bytes=local_mem_bytes,
        cmd_queue_entries=cmd_queue_entries,
        cmp_queue_entries=cmp_queue_entries,
        rx_debug_queue_entries=rx_debug_queue_entries,
        boot_addr=boot_addr,
    )
    if explicit_overrides:
        raise ValueError("family-lane preset cannot be combined with explicit overrides")
    resolved_summary_path = summary_path or _default_family_lane_preset_summary_path(
        preset,
        lab_root=lab_root,
    )
    return run_family_lane(
        preset=preset,
        summary_path=resolved_summary_path,
        lab_root=lab_root,
        runner=runner,
    )


def run_family_lane_matrix(families: list[str] | None = None,
                           *,
                           preset: str | None = None,
                           sim_time: str | None = None,
                           mesh_size: int | None = None,
                           hart_isa: str | None = None,
                           local_mem_bytes: int | None = None,
                           cmd_queue_entries: int | None = None,
                           cmp_queue_entries: int | None = None,
                           rx_debug_queue_entries: int | None = None,
                           boot_addr: int | None = None,
                           summary_path: Path | None = None,
                           lab_root: Path = LAB_ROOT,
                           runner: Runner = run_command) -> dict[str, Any]:
    explicit_overrides = _family_lane_overrides(
        sim_time=sim_time,
        mesh_size=mesh_size,
        hart_isa=hart_isa,
        local_mem_bytes=local_mem_bytes,
        cmd_queue_entries=cmd_queue_entries,
        cmp_queue_entries=cmp_queue_entries,
        rx_debug_queue_entries=rx_debug_queue_entries,
        boot_addr=boot_addr,
    )
    preset_payload: dict[str, Any] | None = None
    if preset is not None:
        if families:
            raise ValueError("family-lane-matrix preset cannot be combined with explicit --family")
        if explicit_overrides:
            raise ValueError("family-lane-matrix preset cannot be combined with explicit overrides")
        preset_payload = _resolve_family_lane_preset(preset, mode="matrix")
        resolved_families = list(preset_payload["families"])
        overrides = dict(preset_payload.get("overrides") or {})
        overrides.update(explicit_overrides)
    else:
        resolved_families = _resolve_family_lane_matrix_families(families, lab_root=lab_root)
        overrides = explicit_overrides
    if not overrides:
        raise ValueError("family-lane-matrix requires at least one override")

    family_rows: list[dict[str, Any]] = []
    for family in resolved_families:
        lane_summary = run_family_lane(
            family=family,
            **_family_lane_override_kwargs(overrides),
            lab_root=lab_root,
            runner=runner,
        )
        family_rows.append(
            {
                "family": str(lane_summary.get("family", family)),
                "status": str(lane_summary.get("status", "FAIL")),
                "summary_path": lane_summary.get("summary_path"),
                "lane_id": lane_summary.get("lane_id"),
                "lane_root": lane_summary.get("lane_root"),
                "lane_overrides": dict(lane_summary.get("lane_overrides") or overrides),
                "gate_reasons": list(lane_summary.get("gate_reasons", [])),
                "runtime_bridge_build_preflight_rollup": dict(
                    (lane_summary.get("runtime_bridge", {}) or {}).get("build_preflight_rollup") or {}
                ),
            }
        )

    matrix_id = _surface_digest(
        {
            "families": _normalized_surface_items(resolved_families),
            "overrides": overrides,
        }
    )
    if preset is not None:
        resolved_summary_path = summary_path or _default_family_lane_matrix_preset_summary_path(
            preset,
            lab_root=lab_root,
        )
    else:
        resolved_summary_path = summary_path or default_reference_path(
            f"family-lane-matrix-subset-{matrix_id}",
            lab_root=lab_root,
        )
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_DATED_FAMILY_LANE_MATRIX,
            scope="research_subset_lane_matrix",
            producer="riscv_snn_lab.run_family_lane_matrix",
        ),
        "gate_name": "riscv_snn_family_lane_matrix",
        "canonical_surface": False,
        "lane_matrix_id": matrix_id,
        "requested_families": resolved_families,
        "lane_overrides": overrides,
        "count": len(family_rows),
        "all_ok": all(row["status"] == "PASS" for row in family_rows),
        "families": family_rows,
        "runtime_bridge_build_preflight_rollup": _matrix_build_preflight_rollup(family_rows),
    }
    if preset is not None and preset_payload is not None:
        summary["preset"] = preset
        summary["preset_name"] = preset
        summary["preset_description"] = str(preset_payload.get("description", ""))
        summary["preset_research_surface_role"] = str(preset_payload.get("research_surface_role", "unknown"))
        summary["preset_included_in_stable_authority"] = bool(
            preset_payload.get("included_in_stable_authority", False)
        )
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def run_family_lane_matrix_preset(preset: str,
                                  *,
                                  sim_time: str | None = None,
                                  mesh_size: int | None = None,
                                  hart_isa: str | None = None,
                                  local_mem_bytes: int | None = None,
                                  cmd_queue_entries: int | None = None,
                                  cmp_queue_entries: int | None = None,
                                  rx_debug_queue_entries: int | None = None,
                                  boot_addr: int | None = None,
                                  summary_path: Path | None = None,
                                  lab_root: Path = LAB_ROOT,
                                  runner: Runner = run_command) -> dict[str, Any]:
    explicit_overrides = _family_lane_overrides(
        sim_time=sim_time,
        mesh_size=mesh_size,
        hart_isa=hart_isa,
        local_mem_bytes=local_mem_bytes,
        cmd_queue_entries=cmd_queue_entries,
        cmp_queue_entries=cmp_queue_entries,
        rx_debug_queue_entries=rx_debug_queue_entries,
        boot_addr=boot_addr,
    )
    if explicit_overrides:
        raise ValueError("family-lane-matrix preset cannot be combined with explicit overrides")
    resolved_summary_path = summary_path or _default_family_lane_matrix_preset_summary_path(
        preset,
        lab_root=lab_root,
    )
    return run_family_lane_matrix(
        families=None,
        preset=preset,
        summary_path=resolved_summary_path,
        lab_root=lab_root,
        runner=runner,
    )


def _add_family_lane_override_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sim-time",
        default=None,
        help="Override platform.stop.simulation_time for both baseline and runtime bridge specs",
    )
    parser.add_argument(
        "--mesh-size",
        type=int,
        default=None,
        help="Override platform.mesh_size for both baseline and runtime bridge specs",
    )
    parser.add_argument(
        "--hart-isa",
        default=None,
        help="Override runtime bridge workload.params.hart_isa",
    )
    parser.add_argument(
        "--local-mem-bytes",
        type=lambda value: int(value, 0),
        default=None,
        help="Override runtime bridge workload.params.local_mem_bytes",
    )
    parser.add_argument(
        "--cmd-queue-entries",
        type=lambda value: int(value, 0),
        default=None,
        help="Override runtime bridge workload.params.cmd_queue_entries",
    )
    parser.add_argument(
        "--cmp-queue-entries",
        type=lambda value: int(value, 0),
        default=None,
        help="Override runtime bridge workload.params.cmp_queue_entries",
    )
    parser.add_argument(
        "--rx-debug-queue-entries",
        type=lambda value: int(value, 0),
        default=None,
        help="Override runtime bridge workload.params.rx_debug_queue_entries",
    )
    parser.add_argument(
        "--boot-addr",
        type=lambda value: int(value, 0),
        default=None,
        help="Override runtime bridge workload.params.boot_addr",
    )


def _sample_role(program: str,
                 sample_manifest: dict[str, Any] | None,
                 *,
                 lab_root: Path = LAB_ROOT) -> str:
    sample = {}
    if sample_manifest:
        sample = sample_manifest.get("samples", {}).get(program, {})
    if sample:
        return "canonical" if sample.get("canonical_sample") else "additive reference"
    if toolchain_source_dir(program, lab_root=lab_root).exists():
        return "toolchain bridge"
    return "unknown"


def _sample_target(program: str,
                   sample_manifest: dict[str, Any] | None,
                   *,
                   lab_root: Path = LAB_ROOT) -> str:
    sample = {}
    if sample_manifest:
        sample = sample_manifest.get("samples", {}).get(program, {})
    if sample:
        return sample.get("description", "TODO")
    if toolchain_source_dir(program, lab_root=lab_root).exists():
        return "以真实 bare-metal toolchain 复刻 builder reference 的 control-plane 契约，并保留独立 replay 资产。"
    return "TODO"


def register_run(program: str,
                 run_dir: Path,
                 *,
                 manifest_path: Path | None = None,
                 lab_root: Path = LAB_ROOT,
                 sample_manifest: dict[str, Any] | None = None) -> Path:
    resolved_run_dir = run_dir.resolve()
    meta_path = resolved_run_dir / "meta.json"
    hist_spec_path = resolved_run_dir / "inputs" / "spec.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing run metadata: {meta_path}")
    if not hist_spec_path.exists():
        raise FileNotFoundError(f"missing run spec: {hist_spec_path}")

    meta = _load_json(meta_path)
    hist_spec = _load_json(hist_spec_path)
    lab_elf = default_elf_path(program, lab_root=lab_root).resolve()
    lab_spec = default_spec_path(program, lab_root=lab_root).resolve()
    if not lab_elf.exists():
        raise FileNotFoundError(f"missing lab firmware: {lab_elf}")
    if not lab_spec.exists():
        raise FileNotFoundError(f"missing lab spec: {lab_spec}")

    hist_fw = Path(hist_spec["workload"]["params"]["firmware_elf"]).resolve()
    validation = _validation_summary(resolved_run_dir)
    run_meta = meta.get("run", {})
    sample_manifest = sample_manifest or {}
    output_path = (manifest_path or default_manifest_path(program, lab_root=lab_root)).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    toolchain_dir = toolchain_source_dir(program, lab_root=lab_root)

    relationship_lines = []
    if lab_spec.read_text(encoding="utf-8") == hist_spec_path.read_text(encoding="utf-8"):
        relationship_lines.append("  - Lab spec 与历史输入 spec 字节级完全一致。")
    else:
        relationship_lines.append("  - Lab spec 与历史输入 spec 存在差异，需要人工比对。")
    if lab_elf == hist_fw and _sha256(lab_elf) == _sha256(hist_fw):
        relationship_lines.append("  - 历史运行直接使用 lab-local firmware 路径，且哈希一致。")
    else:
        relationship_lines.append("  - 历史 firmware 与 lab-local firmware 路径或哈希不同，需要人工核验。")

    pass_render = "\n".join(f"  - `{line}`" for line in validation["pass_lines"]) or "  - `TODO`"
    warn_fail_render = "\n".join(
        f"  - `{line}`"
        for line in [*validation["warn_lines"], *validation["fail_lines"]]
    ) or "  - 无 WARN / FAIL"
    if toolchain_dir.exists():
        replay_block = f"""cd "{toolchain_dir}"
make

cd "{SST_DRAM_SI_ROOT}"
python3 "./tools/mesh_spec_cli.py" validate "{lab_spec}"
./tools/run_mesh_with_time.sh --spec "{lab_spec}" """
    else:
        replay_block = f"""python3 "{GENERATOR_SCRIPT}" \\
  --program {program} \\
  --elf "{lab_elf}" \\
  --spec "{lab_spec}"

cd "{SST_DRAM_SI_ROOT}"
python3 "./tools/mesh_spec_cli.py" validate "{lab_spec}"
./tools/run_mesh_with_time.sh --spec "{lab_spec}" """

    manifest = f"""# {output_path.stem}

## 1. 基本信息

- 记录名：`{output_path.stem}`
- 日期：`{run_meta.get('created_utc', dt.datetime.now(dt.timezone.utc).isoformat())[:10]}`
- 样例程序：`{program}`
- 类型：`{_sample_role(program, sample_manifest, lab_root=lab_root)}`
- 目标：{_sample_target(program, sample_manifest, lab_root=lab_root)}
- 状态：`{validation["summary"]}`

## 2. Lab 资产

- Firmware ELF：
  - path：`{lab_elf}`
  - sha256：`{_sha256(lab_elf)}`
  - bytes：`{lab_elf.stat().st_size}`
- Replay spec JSON：
  - path：`{lab_spec}`
  - sha256：`{_sha256(lab_spec)}`
  - bytes：`{lab_spec.stat().st_size}`

## 3. 真实运行登记

- 历史 run id：`{run_meta.get('run_id', resolved_run_dir.name)}`
- 历史 run dir：`{resolved_run_dir}`
- 历史输入 spec：
  - path：`{hist_spec_path}`
  - sha256：`{_sha256(hist_spec_path)}`
  - bytes：`{hist_spec_path.stat().st_size}`
- 历史 firmware：
  - path：`{hist_fw}`
  - sha256：`{_sha256(hist_fw)}`
- Lab spec 与历史 spec 的关系：
{relationship_lines[0]}
- Lab firmware 与历史 firmware 的关系：
{relationship_lines[1]}

## 4. 历史环境摘要

- created_utc：`{run_meta.get('created_utc', 'unknown')}`
- hostname：`{run_meta.get('hostname', 'unknown')}`
- mesh_size：`{hist_spec['platform']['mesh_size']}`
- num_pes：`{hist_spec['platform']['mesh_size'] * hist_spec['platform']['mesh_size']}`
- sim_time：`{hist_spec['platform']['stop']['simulation_time']}`
- exec_mode：`{hist_spec['platform']['exec_mode']}`
- workload_impl：`{hist_spec['workload']['impl']}`
- global_step_sync_enable：`{int(bool(hist_spec['control']['global_step_sync_enable']))}`

## 5. 验证结果

- Lab spec validate：`参见同名 replay spec，可使用 wrapper validate 复现`
- 历史 validator summary：`{validation["summary"]}`
- 关键 PASS：
{pass_render}
- 关键 WARN / FAIL：
{warn_fail_render}

## 6. 关键输出文件

| 路径 | 角色 |
|---|---|
| `{resolved_run_dir / 'meta.json'}` | 运行元数据 |
| `{resolved_run_dir / 'validation.log'}` | validator 结果 |
| `{resolved_run_dir / 'essential_summary_mesh.json'}` | 关键汇总输出 |
| `{resolved_run_dir / 'mesh_run.log'}` | SST 运行日志 |
| `{hist_spec_path}` | 运行时实际输入 spec |

## 7. 推荐 replay 路径

```bash
{replay_block}
```

## 8. 备注

- 这份文件由 `riscv_snn_lab.py register` 生成草稿，并保持 authority 继续来自主实现目录。
- 如果后续需要补充更多运行解释，应该在本文件上追加，而不是把 run 结论留在聊天记录里。
"""
    output_path.write_text(manifest, encoding="utf-8")
    return output_path


def _print_completed_process(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)


def explain_sidecar_surface(*, lab_root: Path = LAB_ROOT) -> str:
    supplementary_surface_authority = _resolve_authority_path(
        lab_root=lab_root,
        default_path=SUPPLEMENTARY_SURFACE_AUTHORITY_PATH,
    )
    return "\n".join(
        [
            f"stable_top_level_gate: {ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE}",
            f"dated_equivalence_matrix: {ARTIFACT_ROLE_DATED_EQUIV_MATRIX}",
            f"dated_abi_authority_audit: {ARTIFACT_ROLE_DATED_ABI_AUDIT}",
            f"dated_nightly_index: {ARTIFACT_ROLE_DATED_NIGHTLY_INDEX}",
            f"stable_history_rollup: {ARTIFACT_ROLE_STABLE_HISTORY_ROLLUP}",
            f"supplementary_surface_authority: {supplementary_surface_authority}",
            "dated nightly index is not the equivalence authority",
        ]
    )


def explain_mainline_surface(*, lab_root: Path = LAB_ROOT) -> str:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    required_families = ", ".join(authority.get("required_families", [])) or "none"
    primary_optional_group = _mainline_primary_optional_group(lab_root=lab_root) or "none"
    mainline_refresh_default_group = _mainline_refresh_default_group(lab_root=lab_root) or "none"
    lines = [
        f"mainline_gate_authority: {MAINLINE_GATE_AUTHORITY_PATH if lab_root == LAB_ROOT else lab_root / 'spec_authority' / 'riscv_snn_mainline_gate_v1.json'}",
        f"required_families: {required_families}",
        f"primary_optional_group: {primary_optional_group}",
        f"mainline_refresh_default_group: {mainline_refresh_default_group}",
    ]
    for group, payload in sorted(_mainline_optional_groups(lab_root=lab_root).items()):
        lines.append(f"{group}: {', '.join(payload.get('families', [])) or 'none'}")
    lines.append(f"stable_top_level_gate: {stable_reference_path('nightly-sidecar-report', lab_root=lab_root)}")
    return "\n".join(lines)


def explain_runtime_gate_surface(family: str, *, lab_root: Path = LAB_ROOT) -> str:
    authority = load_runtime_gate_authority(lab_root=lab_root)
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    required_checks = ", ".join(family_policy.get("required_checks", [])) or "none"
    stable_reason_ids = ", ".join(authority.get("reason_ids", [])) or "none"
    return "\n".join(
        [
            f"runtime_gate_authority: {_resolve_authority_path(lab_root=lab_root, default_path=RUNTIME_GATE_AUTHORITY_PATH)}",
            f"family: {family}",
            f"fault_mode: {family_policy.get('fault_mode', 'none')}",
            f"progress_mode: {family_policy.get('progress_mode', 'none')}",
            f"fault_lifecycle_mode: {family_policy.get('fault_lifecycle_mode', 'none')}",
            f"timing_mode: {family_policy.get('timing_mode', 'none')}",
            f"queue_mode: {family_policy.get('queue_mode', 'none')}",
            f"reference_program_profile: {family_policy.get('reference_program_profile', 'none')}",
            f"required_checks: {required_checks}",
            f"allowed_completion_signature: {family_policy.get('allowed_completion_signature', 'none')}",
            f"allowed_fault_signature: {family_policy.get('allowed_fault_signature', 'none')}",
            f"stable_reason_ids: {stable_reason_ids}",
        ]
    )


def explain_program_semantics_surface(family: str, *, lab_root: Path = LAB_ROOT) -> str:
    architecture_authority = load_architecture_model_authority(lab_root=lab_root)
    family_policy = _runtime_gate_family_policy(family, lab_root=lab_root)
    request = _reference_program_request_for_family(
        family,
        family_policy=family_policy,
        architecture_authority=architecture_authority,
    )
    runtime_summary = _reference_program_runtime_summary_from_request(request)
    control_events = {
        event_name
        for step in list(runtime_summary.get("steps") or [])
        for event_name in list(step.get("control_events") or [])
        if str(event_name).strip()
    }
    return "\n".join(
        [
            f"architecture_model_authority: {_resolve_authority_path(lab_root=lab_root, default_path=ARCHITECTURE_MODEL_AUTHORITY_PATH)}",
            f"runtime_gate_authority: {_resolve_authority_path(lab_root=lab_root, default_path=RUNTIME_GATE_AUTHORITY_PATH)}",
            f"family: {family}",
            f"reference_program_profile: {runtime_summary.get('reference_program_profile', 'none')}",
            f"step_names: {', '.join(step.get('step_name', '') for step in runtime_summary.get('steps', [])) or 'none'}",
            f"terminal_states: {', '.join(runtime_summary.get('terminal_states', [])) or 'none'}",
            f"control_events: {', '.join(sorted(control_events)) or 'none'}",
        ]
    )


def export_control_plane_contract_payload(authority: dict[str, Any], *,
                                          authority_path: Path | None = None) -> dict[str, Any]:
    return export_riscv_snn_control_plane_contract.normalize_authority(
        authority,
        authority_path=authority_path,
    )


def render_control_plane_contract_markdown(authority: dict[str, Any], *,
                                           authority_path: Path | None = None) -> str:
    return export_riscv_snn_control_plane_contract.render_markdown(
        authority,
        authority_path=authority_path,
    )


def export_control_plane_contract(*,
                                  authority_path: Path | None = None,
                                  output_path: Path | None = None,
                                  json_output_path: Path | None = None,
                                  lab_root: Path = LAB_ROOT) -> dict[str, str]:
    resolved_authority_path = authority_path or _resolve_authority_path(
        lab_root=lab_root,
        default_path=ACCEL_AUTHORITY_PATH,
    )
    authority = load_accel_authority(lab_root=lab_root)
    resolved_output_path = output_path or stable_markdown_path(
        "riscv-snn-control-plane-contract",
        lab_root=lab_root,
    )
    export_riscv_snn_control_plane_contract.write_markdown(
        authority,
        resolved_output_path,
        authority_path=resolved_authority_path,
    )
    resolved_json_output_path = json_output_path
    if resolved_json_output_path is not None:
        export_riscv_snn_control_plane_contract.write_json(
            authority,
            resolved_json_output_path,
            authority_path=resolved_authority_path,
        )
    return {
        "markdown_path": str(resolved_output_path),
        "json_path": str(resolved_json_output_path) if resolved_json_output_path is not None else "",
    }


def _latest_dated_reference(pattern: str, *, lab_root: Path = LAB_ROOT) -> Path | None:
    candidates = sorted((lab_root / "references").glob(pattern))
    return candidates[-1] if candidates else None


def _latest_optional_group_equivalence_surface(*,
                                               group: str,
                                               lab_root: Path = LAB_ROOT) -> tuple[dict[str, Any] | None, Path | None]:
    matrix_path = _latest_dated_reference(_optional_group_matrix_pattern(group), lab_root=lab_root)
    matrix_payload = _load_json(matrix_path) if matrix_path is not None and matrix_path.exists() else None
    if matrix_payload is not None and matrix_path is not None:
        matrix_payload = dict(matrix_payload)
        matrix_payload.setdefault("summary_path", str(matrix_path))

    singleton_family = _optional_group_singleton_family(group, lab_root=lab_root)
    family_payload: dict[str, Any] | None = None
    family_path: Path | None = None
    if singleton_family is not None:
        family_path = _latest_dated_reference(
            _optional_group_family_equiv_pattern(singleton_family),
            lab_root=lab_root,
        )
        if family_path is not None and family_path.exists():
            payload = _load_json(family_path)
            family_payload = _optional_single_family_equivalence_payload(
                payload,
                group=group,
                family=singleton_family,
                summary_path=str(family_path),
            )

    if matrix_payload is not None and matrix_path is not None:
        if family_payload is not None and family_path is not None:
            matrix_key = _optional_surface_candidate_key(
                matrix_payload,
                summary_path=matrix_path,
                source_kind="group_matrix",
            )
            family_key = _optional_surface_candidate_key(
                family_payload,
                summary_path=family_path,
                source_kind="singleton_family_equivalence",
            )
            if family_key > matrix_key:
                return family_payload, family_path
        return matrix_payload, matrix_path

    if family_payload is not None and family_path is not None:
        return family_payload, family_path
    return None, None


def _optional_group_review_surface(*,
                                   group: str,
                                   families: list[str],
                                   lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    review_path = _latest_dated_reference(f"*-{group.replace('_', '-')}-review.json", lab_root=lab_root)
    payload = _load_json(review_path) if review_path and review_path.exists() else None
    issues: list[str] = []
    decision = None
    reviewer = None
    review_date = None
    if payload is None:
        issues.append("missing")
    else:
        decision = payload.get("decision")
        reviewer = payload.get("reviewer")
        review_date = payload.get("review_date") or _date_from_generated_utc(payload.get("generated_utc"))
        if payload.get("artifact_role") != ARTIFACT_ROLE_DATED_OPTIONAL_GROUP_REVIEW:
            issues.append("artifact_role")
        if str(payload.get("group")) != group:
            issues.append("group")
        if sorted(payload.get("families", [])) != sorted(families):
            issues.append("families")
        if not isinstance(reviewer, str) or not reviewer.strip():
            issues.append("reviewer")
        if not isinstance(decision, str) or not decision.strip():
            issues.append("decision")
        elif decision != "approved":
            issues.append("decision_not_approved")
        if not isinstance(review_date, str) or not review_date:
            issues.append("review_date")

    return {
        "path": str(review_path) if review_path else None,
        "available": payload is not None,
        "ok": not issues,
        "issues": issues,
        "decision": decision,
        "reviewer": reviewer,
        "review_date": review_date,
    }


def _optional_group_reason(group: str, suffix: str) -> str:
    return f"{group}_{suffix}"


def run_family_admission_audit(*,
                               group: str = "queue_optional",
                               summary_path: Path | None = None,
                               lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    authority = load_mainline_gate_authority(lab_root=lab_root)
    runtime_gate_authority = load_runtime_gate_authority(lab_root=lab_root)
    optional_groups = dict(authority.get("optional_groups", {}) or {})
    group_payload = dict(optional_groups.get(group, {}) or {})
    if not group_payload:
        raise ValueError(f"unknown optional admission group: {group}")
    promotion_contract = dict((authority.get("promotion_contract", {}) or {}).get(group, {}) or {})
    families = sorted(group_payload.get("families", []))
    group_equivalence, group_equiv_path = _latest_optional_group_equivalence_surface(
        group=group,
        lab_root=lab_root,
    )
    sidecar_path = stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    history_path = stable_reference_path("nightly-history-index", lab_root=lab_root)
    sidecar_report = _load_json(sidecar_path) if sidecar_path.exists() else None
    history_index = _load_json(history_path) if history_path.exists() else None
    group_history = _optional_history_surface(
        group=group,
        live_surface=group_equivalence,
        lab_root=lab_root,
    ) or {}
    latest_family_surface_paths, surface_failures, failing_reason_ids = _equivalence_surface_failure_summary(
        group_equivalence,
    )
    freshness_mode = str(promotion_contract.get("multi_date_freshness_mode") or "all_dates")
    freshness_rollup = _optional_history_freshness_rollup(
        group_history,
        mode=freshness_mode,
    )
    review_surface = _optional_group_review_surface(group=group, families=families, lab_root=lab_root)
    reasons: list[str] = []

    if promotion_contract.get("requires_family_equiv_pass") and not bool(group_equivalence and group_equivalence.get("all_ok")):
        reasons.append(_optional_group_reason(group, "equiv_not_green"))
    if promotion_contract.get("requires_multi_date_freshness"):
        if not bool(group_history.get("entry_count")):
            reasons.append(_optional_group_reason(group, "multi_date_freshness_history_missing"))
        elif freshness_rollup["raw_entry_count"] < 2:
            reasons.append(_optional_group_reason(group, "multi_date_freshness_insufficient"))
        elif not freshness_rollup["effective_all_dates_ok"]:
            reasons.append(_optional_group_reason(group, "multi_date_freshness_not_green"))
    if promotion_contract.get("requires_reason_taxonomy_clean") and not _runtime_gate_reason_ids(lab_root=lab_root):
        reasons.append("runtime_gate_reason_taxonomy_missing")
    if promotion_contract.get("requires_explicit_review") and not review_surface["ok"]:
        if not review_surface["available"]:
            reasons.append("explicit_review_record_missing")
        elif "decision_not_approved" in review_surface["issues"]:
            reasons.append("explicit_review_not_approved")
        else:
            reasons.append("explicit_review_record_invalid")
    if sidecar_report and any(family in sidecar_report.get("required_families", []) for family in families):
        reasons.append("optional_family_unexpectedly_promoted")

    promotion_ready = not reasons
    resolved_summary_path = summary_path or default_reference_path(
        f"{group.replace('_', '-')}-admission-audit",
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_DATED_FAMILY_ADMISSION_AUDIT,
            scope="research_only_nonblocking",
            producer="riscv_snn_lab.run_family_admission_audit",
        ),
        "contract_primary": OPTIONAL_ADMISSION_PRIMARY_CONTRACT,
        "primary_contract_fields": list(OPTIONAL_ADMISSION_PRIMARY_FIELDS),
        "compatibility_aliases": {},
        "group": group,
        "families": families,
        "blocking": bool(group_payload.get("blocking", False)),
        "promotion_ready": promotion_ready,
        "reasons": reasons,
        "required_contracts": promotion_contract,
        "mainline_gate_authority_path": str(
            _resolve_authority_path(lab_root=lab_root, default_path=MAINLINE_GATE_AUTHORITY_PATH)
        ),
        "runtime_gate_authority_path": str(
            _resolve_authority_path(lab_root=lab_root, default_path=RUNTIME_GATE_AUTHORITY_PATH)
        ),
        "group_equivalence_path": str(group_equiv_path) if group_equiv_path else None,
        "group_equivalence_all_ok": bool(group_equivalence.get("all_ok")) if group_equivalence else False,
        "latest_family_surface_paths": latest_family_surface_paths,
        "surface_failures": surface_failures,
        "failing_reason_ids": failing_reason_ids,
        "group_history_path": group_history.get("summary_path"),
        "group_history_available": bool(group_history.get("entry_count")),
        "group_history_entry_count": int(group_history.get("entry_count", 0)),
        "group_history_all_dates_ok": bool(group_history.get("all_dates_ok")),
        "group_history_latest_recovered_date": freshness_rollup["latest_recovered_date"],
        "group_history_freshness_mode": freshness_rollup["mode"],
        "group_history_effective_entry_count": freshness_rollup["effective_entry_count"],
        "group_history_effective_all_dates_ok": freshness_rollup["effective_all_dates_ok"],
        "stable_sidecar_path": str(sidecar_path),
        "stable_sidecar_gate_ok": bool(sidecar_report.get("gate_ok")) if sidecar_report else False,
        "stable_history_path": str(history_path),
        "stable_history_latest_date": history_index.get("latest_date") if history_index else None,
        "stable_reason_ids": list(runtime_gate_authority.get("reason_ids", [])),
        "explicit_review_path": review_surface["path"],
        "explicit_review_ok": review_surface["ok"],
        "explicit_review_decision": review_surface["decision"],
        "explicit_review_reviewer": review_surface["reviewer"],
        "explicit_review_date": review_surface["review_date"],
        "current_mainline_status_path": None,
    }
    if group == "queue_optional":
        summary["compatibility_aliases"] = {
            "queue_optional": list(QUEUE_OPTIONAL_ADMISSION_ALIAS_FIELDS)
        }
        summary.update(
            {
                "queue_equivalence_path": summary["group_equivalence_path"],
                "queue_equivalence_all_ok": summary["group_equivalence_all_ok"],
                "queue_history_path": summary["group_history_path"],
                "queue_history_available": summary["group_history_available"],
                "queue_history_entry_count": summary["group_history_entry_count"],
                "queue_history_all_dates_ok": summary["group_history_all_dates_ok"],
                "queue_history_latest_recovered_date": summary["group_history_latest_recovered_date"],
                "queue_history_freshness_mode": summary["group_history_freshness_mode"],
                "queue_history_effective_entry_count": summary["group_history_effective_entry_count"],
                "queue_history_effective_all_dates_ok": summary["group_history_effective_all_dates_ok"],
            }
        )
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    refreshed_surfaces: dict[str, str] = {}
    if sidecar_report is not None:
        refresh_outputs = _refresh_derived_stable_surfaces(
            sidecar_path=sidecar_path,
            lab_root=lab_root,
        )
        refreshed_surfaces = {
            name: str(path)
            for name, path in refresh_outputs.items()
        }
        summary["current_mainline_status_path"] = refreshed_surfaces.get("current_mainline_status_path")
    else:
        summary["current_mainline_status_path"] = None
    summary["refreshed_surfaces"] = refreshed_surfaces
    _write_json(resolved_summary_path, summary)
    return summary


def run_hart_ref(*,
                 profile: str,
                 summary_path: Path | None = None,
                 spike_path: Path | None = None) -> dict[str, Any]:
    return riscv_hart_ref.run_hart_ref(profile, summary_path=summary_path, spike_path=spike_path)


def probe_spike_local(*,
                      summary_path: Path | None = None,
                      lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    resolved_summary_path = summary_path or default_reference_path("spike-local", lab_root=lab_root)
    return riscv_hart_ref.probe_local_spike_env(lab_root=lab_root, summary_path=resolved_summary_path)


def audit_abi_surface(*,
                      authority_path: Path | None = None,
                      summary_path: Path | None = None,
                      lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    resolved_authority_path = authority_path or lab_root / "spec_authority" / "riscv_snn_accel_v1.json"
    resolved_include_path = resolved_authority_path.with_suffix(".inc")
    authority = json.loads(resolved_authority_path.read_text(encoding="utf-8"))
    generated_include_text = export_riscv_snn_abi.render_include_text(authority)
    checked_include_text = resolved_include_path.read_text(encoding="utf-8")

    authority_include_resolved = resolved_include_path.resolve()
    toolchain_results: list[dict[str, Any]] = []
    for program in matrix_programs("toolchain"):
        toolchain_dir = toolchain_source_dir(program, lab_root=lab_root)
        main_path = toolchain_dir / "main.S"
        abi_path = toolchain_dir / "abi.inc"
        main_content = main_path.read_text(encoding="utf-8") if main_path.exists() else ""
        main_uses_abi_bridge = '.include "abi.inc"' in main_content
        abi_bridge_exists = abi_path.exists()
        abi_bridge_line = abi_path.read_text(encoding="utf-8").strip() if abi_bridge_exists else ""
        abi_bridge_target = None
        abi_bridge_resolved = None
        abi_bridge_matches_authority = False
        if abi_bridge_line.startswith('.include "') and abi_bridge_line.endswith('"'):
            abi_bridge_target = abi_bridge_line[len('.include "') : -1]
            resolved_bridge_path = (abi_path.parent / abi_bridge_target).resolve()
            abi_bridge_resolved = str(resolved_bridge_path)
            abi_bridge_matches_authority = resolved_bridge_path == authority_include_resolved
        toolchain_results.append(
            {
                "program": program,
                "toolchain_dir": str(toolchain_dir),
                "main_path": str(main_path),
                "abi_path": str(abi_path),
                "main_uses_abi_bridge": main_uses_abi_bridge,
                "abi_bridge_exists": abi_bridge_exists,
                "abi_bridge_line": abi_bridge_line or None,
                "abi_bridge_target": abi_bridge_target,
                "abi_bridge_resolved": abi_bridge_resolved,
                "abi_bridge_matches_authority": abi_bridge_matches_authority,
                "ok": main_uses_abi_bridge and abi_bridge_exists and abi_bridge_matches_authority,
            }
        )

    resolved_summary_path = summary_path or default_reference_path("abi-audit", lab_root=lab_root)
    summary = {
        **_artifact_metadata(
            role="dated_abi_authority_audit",
            scope="single_abi_authority_surface",
            producer="riscv_snn_lab.audit_abi_surface",
        ),
        "authority_json": str(resolved_authority_path),
        "authority_include": str(resolved_include_path),
        "generated_include_matches_checked_in": generated_include_text == checked_include_text,
        "toolchain_count": len(toolchain_results),
        "toolchain_all_ok": all(result["ok"] for result in toolchain_results),
        "toolchain_programs": toolchain_results,
    }
    summary["all_ok"] = bool(summary["generated_include_matches_checked_in"]) and bool(summary["toolchain_all_ok"])
    _write_json(resolved_summary_path, summary)
    summary["summary_path"] = str(resolved_summary_path)
    return summary


def export_abi_include(*,
                       authority_path: Path | None = None,
                       output_path: Path | None = None) -> Path:
    resolved_authority_path = authority_path or LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.json"
    resolved_output_path = output_path or resolved_authority_path.with_suffix(".inc")
    authority = json.loads(resolved_authority_path.read_text(encoding="utf-8"))
    export_riscv_snn_abi.render_include(authority, resolved_output_path)
    return resolved_output_path


def run_research_postprocess(*,
                             sidecar_path: Path | None = None,
                             research_output_path: Path | None = None,
                             validation_output_path: Path | None = None,
                             lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    resolved_research_output_path = (
        research_output_path or stable_reference_path("riscv-snn-research-report", lab_root=lab_root)
    )
    resolved_validation_output_path = (
        validation_output_path or stable_reference_path("observer-adequacy-validation", lab_root=lab_root)
    )
    report_path = export_riscv_snn_research_report.generate_research_report(
        sidecar_path=resolved_sidecar_path,
        output_path=resolved_research_output_path,
    )
    validation_path = export_riscv_snn_research_report.validate_observer_adequacy_report(
        report_path=report_path,
        output_path=resolved_validation_output_path,
    )
    if resolved_sidecar_path.exists():
        sidecar_report = _load_json(resolved_sidecar_path)
        if sidecar_report.get("artifact_role") == ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
            sidecar_report["research_report_path"] = str(report_path)
            sidecar_report["observer_adequacy_validation_path"] = str(validation_path)
            _write_json(resolved_sidecar_path, sidecar_report)
    return {
        "research_report_path": report_path,
        "observer_adequacy_validation_path": validation_path,
    }


def refresh_observer_surfaces(*,
                              sample_paths: list[Path] | None = None,
                              compact_observer_history_since_latest_recovery: bool = False,
                              sidecar_path: Path | None = None,
                              observer_summary_path: Path | None = None,
                              optional_promotion_dossier_path: Path | None = None,
                              lab_root: Path = LAB_ROOT,
                              runner: Runner = run_command) -> dict[str, Path]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    if not resolved_sidecar_path.exists():
        raise FileNotFoundError(f"stable sidecar report missing: {resolved_sidecar_path}")
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    resolved_observer_summary_path = observer_summary_path or Path(
        sidecar_report.get("observer_summary_path")
        or stable_reference_path("nightly-sidecar-observer-summary", lab_root=lab_root)
    )
    observer_history_path = stable_reference_path("observer-full-equivalence-history", lab_root=lab_root)
    observer_history: dict[str, Any] | None = None
    sidecar_report_changed = False
    should_refresh_observer_history = bool(sample_paths) or bool(
        compact_observer_history_since_latest_recovery
    ) or observer_history_path.exists()
    if should_refresh_observer_history:
        observer_history = refresh_observer_history_surface(
            sample_paths=sample_paths,
            compact_since_latest_recovery=compact_observer_history_since_latest_recovery,
            lab_root=lab_root,
            output_path=observer_history_path,
        )
    if observer_history is not None:
        sidecar_report = dict(sidecar_report)
        sidecar_report["observer_full_equivalence_history"] = observer_history
        sidecar_report_changed = True
    refreshed_optional_group_report = _refresh_report_optional_group_surfaces(
        sidecar_report,
        lab_root=lab_root,
    )
    if refreshed_optional_group_report != sidecar_report:
        sidecar_report = refreshed_optional_group_report
        sidecar_report_changed = True
    if sidecar_report_changed:
        _write_json(resolved_sidecar_path, sidecar_report)
    try:
        refresh_stat_snapshot_family_surface(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
            refresh_derived_surfaces=False,
            runner=runner,
        )
    except FileNotFoundError:
        pass
    try:
        refresh_reference_compare_surface(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
            refresh_derived_surfaces=False,
        )
    except FileNotFoundError:
        pass
    try:
        refresh_reference_program_compare_surface(
            sidecar_path=resolved_sidecar_path,
            lab_root=lab_root,
            refresh_derived_surfaces=False,
        )
    except FileNotFoundError:
        pass

    return {
        **_refresh_derived_stable_surfaces(
            sidecar_path=resolved_sidecar_path,
            observer_summary_path=resolved_observer_summary_path,
            optional_promotion_dossier_path=optional_promotion_dossier_path,
            lab_root=lab_root,
        ),
        "observer_history_path": observer_history_path,
    }


def export_research_report(*,
                           sidecar_path: Path | None = None,
                           output_path: Path | None = None,
                           validation_output_path: Path | None = None,
                           lab_root: Path = LAB_ROOT) -> Path:
    outputs = run_research_postprocess(
        sidecar_path=sidecar_path,
        research_output_path=output_path,
        validation_output_path=validation_output_path,
        lab_root=lab_root,
    )
    return outputs["research_report_path"]


def validate_observer_adequacy(*,
                               report_path: Path | None = None,
                               output_path: Path | None = None,
                               lab_root: Path = LAB_ROOT) -> Path:
    resolved_report_path = report_path or stable_reference_path("riscv-snn-research-report", lab_root=lab_root)
    resolved_output_path = output_path or stable_reference_path("observer-adequacy-validation", lab_root=lab_root)
    return export_riscv_snn_research_report.validate_observer_adequacy_report(
        report_path=resolved_report_path,
        output_path=resolved_output_path,
    )


def render_mainline_status_markdown(sidecar_report: dict[str, Any],
                                    *,
                                    sidecar_path: Path,
                                    observer_summary: dict[str, Any] | None,
                                    observer_summary_path: Path | None,
                                    research_report: dict[str, Any] | None,
                                    research_report_path: Path | None,
                                    validation_report: dict[str, Any] | None,
                                    validation_report_path: Path | None,
                                    optional_group_names: list[str],
                                    optional_group_rollups: dict[str, dict[str, Any]],
                                    optional_admission_surfaces: dict[str, dict[str, Any]],
                                    optional_admission_paths: dict[str, Path],
                                    runtime_gate_authority: dict[str, Any],
                                    runtime_gate_authority_path: Path) -> str:
    lab_root = sidecar_path.parent.parent
    primary_optional_group = _mainline_primary_optional_group(lab_root=lab_root)
    mainline_refresh_default_group = _mainline_refresh_default_group(lab_root=lab_root)
    ordered_optional_groups = _ordered_optional_groups(
        optional_group_names,
        primary_group=primary_optional_group,
    )
    observer_surface = dict(
        (((observer_summary or {}).get("optional_surfaces") or {}).get("full_equivalence") or {})
    )
    queue_observer_surface = dict(optional_group_rollups.get("queue_optional") or {})
    supplementary_surface_histories = {
        name: dict(payload or {})
        for name, payload in dict((observer_summary or {}).get("supplementary_surface_histories") or {}).items()
        if isinstance(payload, dict)
    }
    observer_adequacy = dict((research_report or {}).get("observer_adequacy") or {})
    validation_payload = dict(validation_report or {})
    active_optional_group = _active_optional_group(
        optional_group_names,
        primary_group=primary_optional_group,
        optional_group_rollups=optional_group_rollups,
        optional_admission_surfaces=optional_admission_surfaces,
        optional_admission_paths=optional_admission_paths,
    )
    primary_optional_rollup = dict(optional_group_rollups.get(active_optional_group or "") or {})
    primary_optional_admission = dict(optional_admission_surfaces.get(active_optional_group or "") or {})
    primary_optional_admission_path = optional_admission_paths.get(active_optional_group or "")
    completion_consume_check = dict((runtime_gate_authority.get("checks") or {}).get("completion_consumed_covers_visible") or {})
    stable_surface_refresh = dict(sidecar_report.get("stable_surface_refresh") or {})
    supplementary_surfaces = _report_supplementary_surfaces(sidecar_report, lab_root=lab_root)
    compare_surface = dict(supplementary_surfaces.get("compare") or {})
    compare_rollup = (
        _supplementary_surface_rollup("compare", compare_surface, lab_root=lab_root)
        if compare_surface
        else {}
    )
    reference_compare_surface = dict(supplementary_surfaces.get("reference_compare") or {})
    reference_compare_rollup = _supplementary_surface_rollup(
        "reference_compare",
        reference_compare_surface if reference_compare_surface else None,
        lab_root=lab_root,
    )
    reference_program_compare_surface = dict(
        supplementary_surfaces.get("reference_program_compare") or {}
    )
    reference_program_compare_rollup = _supplementary_surface_rollup(
        "reference_program_compare",
        reference_program_compare_surface if reference_program_compare_surface else None,
        lab_root=lab_root,
    )
    stat_snapshot_family_surface = dict(supplementary_surfaces.get("stat_snapshot_family") or {})
    stat_snapshot_family_rollup = _supplementary_surface_rollup(
        "stat_snapshot_family",
        stat_snapshot_family_surface if stat_snapshot_family_surface else None,
        lab_root=lab_root,
    )
    supplementary_surface_authority_path = _resolve_authority_path(
        lab_root=lab_root,
        default_path=SUPPLEMENTARY_SURFACE_AUTHORITY_PATH,
    )
    compare_history = dict(supplementary_surface_histories.get("compare") or {})
    reference_compare_history = dict(supplementary_surface_histories.get("reference_compare") or {})
    reference_program_compare_history = dict(
        supplementary_surface_histories.get("reference_program_compare") or {}
    )
    stat_snapshot_family_history = dict(
        supplementary_surface_histories.get("stat_snapshot_family") or {}
    )
    surface_generated_utc = (
        stable_surface_refresh.get("refreshed_utc")
        or sidecar_report.get("generated_utc")
    )
    accepted_fault_rows: list[tuple[str, str]] = []
    for family, payload in sorted((runtime_gate_authority.get("families") or {}).items()):
        row = dict(payload or {})
        if row.get("fault_mode") != "accepted_fault_required":
            continue
        signature = str(row.get("allowed_completion_signature") or "").strip()
        if signature:
            accepted_fault_rows.append((family, signature))

    def _fmt(value: Any) -> str:
        if value is None:
            return "none"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) if value else "none"
        return str(value)

    optional_surface_lines: list[str] = []
    optional_freshness_lines: list[str] = []
    optional_admission_lines: list[str] = []
    optional_failure_lines: list[str] = []
    for group in ordered_optional_groups:
        rollup = dict(optional_group_rollups.get(group) or {})
        admission = dict(optional_admission_surfaces.get(group) or {})
        admission_path = optional_admission_paths.get(group)
        if group != primary_optional_group:
            optional_surface_lines.append(f"- optional admission audit `{group}`: `{admission_path or 'none'}`")
        optional_freshness_lines.extend(
            [
                f"- `{group}.latest_date = {_fmt(rollup.get('latest_date'))}`",
                f"- `{group}.entry_count = {_fmt(rollup.get('entry_count'))}`",
                f"- `{group}.all_dates_ok = {_fmt(rollup.get('all_dates_ok'))}`",
                f"- `{group}.history_contract = {_fmt(rollup.get('history_contract'))}`",
                f"- `{group}.freshness_mode = {_fmt(rollup.get('freshness_mode'))}`",
                f"- `{group}.effective_entry_count = {_fmt(rollup.get('effective_entry_count'))}`",
                f"- `{group}.effective_all_dates_ok = {_fmt(rollup.get('effective_all_dates_ok'))}`",
            ]
        )
        optional_admission_lines.extend(
            [
                f"- `{group}.promotion_ready = {_fmt(admission.get('promotion_ready'))}`",
                f"- `{group}.explicit_review_ok = {_fmt(admission.get('explicit_review_ok'))}`",
                f"- `{group}.blocking = {_fmt(admission.get('blocking'))}`",
            ]
        )
        optional_failure_lines.append(
            f"- `{group}.failing_reason_ids = {_fmt(admission.get('failing_reason_ids'))}`"
        )
        for family, reasons in sorted((admission.get("surface_failures") or {}).items()):
            optional_failure_lines.append(f"- `{family}`: `{_fmt(reasons)}`")

    lines = [
        "# riscv_snn current mainline status",
        "",
        f"- Generated UTC: `{surface_generated_utc}`",
        "- Role: shared readable current-state surface derived from stable experimental references",
        "",
        "## Stable Surfaces",
        f"- stable top-level gate: `{sidecar_path}`",
        f"- stable observer summary: `{observer_summary_path or 'none'}`",
        f"- stable research report: `{research_report_path or 'none'}`",
        f"- stable adequacy validation: `{validation_report_path or 'none'}`",
        f"- primary optional group: `{_fmt(primary_optional_group)}`",
        f"- active optional group: `{_fmt(active_optional_group)}`",
        f"- stable surface refresh UTC: `{_fmt(stable_surface_refresh.get('refreshed_utc'))}`",
        f"- stable surface refresh observer summary: `{_fmt(stable_surface_refresh.get('observer_summary_path'))}`",
        f"- stable surface refresh current mainline: `{_fmt(stable_surface_refresh.get('current_mainline_status_path'))}`",
        f"- stable supplementary surface history: `{_fmt(sidecar_report.get('supplementary_surface_history_path'))}`",
        f"- supplementary surface authority: `{_fmt(supplementary_surface_authority_path)}`",
        f"- stable surface refresh audit: `{_fmt(sidecar_report.get('stable_surface_refresh_audit_path'))}`",
        f"- stable surface refresh optional promotion dossier: `{_fmt(stable_surface_refresh.get('optional_promotion_dossier_path'))}`",
        f"- latest optional admission audit: `{primary_optional_admission_path or 'none'}`",
        *optional_surface_lines,
        f"- runtime gate authority: `{runtime_gate_authority_path}`",
        "",
        "## Top-Level Gate",
        f"- `gate_ok = {_fmt(sidecar_report.get('gate_ok'))}`",
        f"- `with_equivalence = {_fmt(sidecar_report.get('with_equivalence'))}`",
        f"- `with_full_equivalence = {_fmt(sidecar_report.get('with_full_equivalence'))}`",
        f"- `required_families = {_fmt(sidecar_report.get('required_families'))}`",
        "",
        "## Observer Closure",
        f"- `entry_count = {_fmt(observer_surface.get('entry_count'))}`",
        f"- `first_fail_date = {_fmt(observer_surface.get('first_fail_date'))}`",
        f"- `latest_recovered_date = {_fmt(observer_surface.get('latest_recovered_date'))}`",
        f"- `all_ok_latest = {_fmt(observer_surface.get('all_ok_latest'))}`",
        f"- `history_contract = {_fmt(observer_surface.get('history_contract'))}`",
        f"- `refresh_mode = {_fmt(observer_surface.get('refresh_mode'))}`",
        f"- `effective_entry_count = {_fmt(observer_surface.get('effective_entry_count'))}`",
        f"- `effective_all_dates_ok = {_fmt(observer_surface.get('effective_all_dates_ok'))}`",
        "",
        "## Research / Validation",
        f"- `observer_adequacy.status = {_fmt(observer_adequacy.get('status'))}`",
        f"- `status = {_fmt(validation_payload.get('status'))}`",
        f"- `mismatch_count = {_fmt(validation_payload.get('mismatch_count'))}`",
        "",
        "## Supplementary Surfaces",
        f"- `compare.status = {_fmt(compare_rollup.get('status'))}`",
        f"- `compare.healthy = {_fmt(compare_rollup.get('healthy'))}`",
        f"- `compare.freshness_ok = {_fmt(compare_rollup.get('freshness_ok'))}`",
        f"- `compare.present = {_fmt(compare_surface.get('present'))}`",
        f"- `compare.gate_ok = {_fmt(compare_surface.get('gate_ok'))}`",
        f"- `compare.latest_date = {_fmt(compare_surface.get('latest_date'))}`",
        f"- `compare.stale = {_fmt(compare_surface.get('stale'))}`",
        f"- `compare.freshness_mode = {_fmt(compare_surface.get('freshness_mode'))}`",
        (
            "- `compare.effective_all_dates_ok = "
            f"{_fmt(compare_surface.get('effective_all_dates_ok'))}`"
        ),
        f"- `compare.history_contract = {_fmt(compare_history.get('history_contract'))}`",
        f"- `compare.entry_count = {_fmt(compare_history.get('entry_count'))}`",
        f"- `compare.latest_recovered_date = {_fmt(compare_history.get('latest_recovered_date'))}`",
        f"- `compare.report_path = {_fmt(compare_surface.get('report_path'))}`",
        (
            "- `compare.current_mainline_status_path = "
            f"{_fmt(compare_surface.get('current_mainline_status_path'))}`"
        ),
        f"- `compare.summary_md_path = {_fmt(compare_surface.get('summary_md_path'))}`",
        f"- `compare.load_error = {_fmt(compare_surface.get('load_error'))}`",
        f"- `reference_compare.status = {_fmt(reference_compare_rollup.get('status'))}`",
        f"- `reference_compare.healthy = {_fmt(reference_compare_rollup.get('healthy'))}`",
        f"- `reference_compare.freshness_ok = {_fmt(reference_compare_rollup.get('freshness_ok'))}`",
        f"- `reference_compare.present = {_fmt(reference_compare_surface.get('present'))}`",
        f"- `reference_compare.gate_ok = {_fmt(reference_compare_surface.get('gate_ok'))}`",
        f"- `reference_compare.latest_date = {_fmt(reference_compare_surface.get('latest_date'))}`",
        f"- `reference_compare.stale = {_fmt(reference_compare_surface.get('stale'))}`",
        (
            "- `reference_compare.freshness_mode = "
            f"{_fmt(reference_compare_surface.get('freshness_mode'))}`"
        ),
        (
            "- `reference_compare.effective_all_dates_ok = "
            f"{_fmt(reference_compare_surface.get('effective_all_dates_ok'))}`"
        ),
        (
            "- `reference_compare.history_contract = "
            f"{_fmt(reference_compare_history.get('history_contract'))}`"
        ),
        f"- `reference_compare.entry_count = {_fmt(reference_compare_history.get('entry_count'))}`",
        (
            "- `reference_compare.latest_recovered_date = "
            f"{_fmt(reference_compare_history.get('latest_recovered_date'))}`"
        ),
        (
            "- `reference_compare.report_path = "
            f"{_fmt(reference_compare_surface.get('report_path'))}`"
        ),
        (
            "- `reference_compare.current_mainline_status_path = "
            f"{_fmt(reference_compare_surface.get('current_mainline_status_path'))}`"
        ),
        (
            "- `reference_compare.summary_md_path = "
            f"{_fmt(reference_compare_surface.get('summary_md_path'))}`"
        ),
        (
            "- `reference_compare.load_error = "
            f"{_fmt(reference_compare_surface.get('load_error'))}`"
        ),
        (
            "- `reference_program_compare.status = "
            f"{_fmt(reference_program_compare_rollup.get('status'))}`"
        ),
        (
            "- `reference_program_compare.healthy = "
            f"{_fmt(reference_program_compare_rollup.get('healthy'))}`"
        ),
        (
            "- `reference_program_compare.freshness_ok = "
            f"{_fmt(reference_program_compare_rollup.get('freshness_ok'))}`"
        ),
        (
            "- `reference_program_compare.present = "
            f"{_fmt(reference_program_compare_surface.get('present'))}`"
        ),
        (
            "- `reference_program_compare.gate_ok = "
            f"{_fmt(reference_program_compare_surface.get('gate_ok'))}`"
        ),
        (
            "- `reference_program_compare.latest_date = "
            f"{_fmt(reference_program_compare_surface.get('latest_date'))}`"
        ),
        (
            "- `reference_program_compare.stale = "
            f"{_fmt(reference_program_compare_surface.get('stale'))}`"
        ),
        (
            "- `reference_program_compare.freshness_mode = "
            f"{_fmt(reference_program_compare_surface.get('freshness_mode'))}`"
        ),
        (
            "- `reference_program_compare.effective_all_dates_ok = "
            f"{_fmt(reference_program_compare_surface.get('effective_all_dates_ok'))}`"
        ),
        (
            "- `reference_program_compare.history_contract = "
            f"{_fmt(reference_program_compare_history.get('history_contract'))}`"
        ),
        (
            "- `reference_program_compare.entry_count = "
            f"{_fmt(reference_program_compare_history.get('entry_count'))}`"
        ),
        (
            "- `reference_program_compare.latest_recovered_date = "
            f"{_fmt(reference_program_compare_history.get('latest_recovered_date'))}`"
        ),
        (
            "- `reference_program_compare.report_path = "
            f"{_fmt(reference_program_compare_surface.get('report_path'))}`"
        ),
        (
            "- `reference_program_compare.current_mainline_status_path = "
            f"{_fmt(reference_program_compare_surface.get('current_mainline_status_path'))}`"
        ),
        (
            "- `reference_program_compare.summary_md_path = "
            f"{_fmt(reference_program_compare_surface.get('summary_md_path'))}`"
        ),
        (
            "- `reference_program_compare.load_error = "
            f"{_fmt(reference_program_compare_surface.get('load_error'))}`"
        ),
        (
            "- `stat_snapshot_family.status = "
            f"{_fmt(stat_snapshot_family_rollup.get('status'))}`"
        ),
        (
            "- `stat_snapshot_family.healthy = "
            f"{_fmt(stat_snapshot_family_rollup.get('healthy'))}`"
        ),
        (
            "- `stat_snapshot_family.freshness_ok = "
            f"{_fmt(stat_snapshot_family_rollup.get('freshness_ok'))}`"
        ),
        (
            "- `stat_snapshot_family.present = "
            f"{_fmt(stat_snapshot_family_surface.get('present'))}`"
        ),
        (
            "- `stat_snapshot_family.gate_ok = "
            f"{_fmt(stat_snapshot_family_surface.get('gate_ok'))}`"
        ),
        (
            "- `stat_snapshot_family.latest_date = "
            f"{_fmt(stat_snapshot_family_surface.get('latest_date'))}`"
        ),
        (
            "- `stat_snapshot_family.stale = "
            f"{_fmt(stat_snapshot_family_surface.get('stale'))}`"
        ),
        (
            "- `stat_snapshot_family.freshness_mode = "
            f"{_fmt(stat_snapshot_family_surface.get('freshness_mode'))}`"
        ),
        (
            "- `stat_snapshot_family.effective_all_dates_ok = "
            f"{_fmt(stat_snapshot_family_surface.get('effective_all_dates_ok'))}`"
        ),
        (
            "- `stat_snapshot_family.history_contract = "
            f"{_fmt(stat_snapshot_family_history.get('history_contract'))}`"
        ),
        (
            "- `stat_snapshot_family.entry_count = "
            f"{_fmt(stat_snapshot_family_history.get('entry_count'))}`"
        ),
        (
            "- `stat_snapshot_family.latest_recovered_date = "
            f"{_fmt(stat_snapshot_family_history.get('latest_recovered_date'))}`"
        ),
        (
            "- `stat_snapshot_family.selector_count = "
            f"{_fmt(stat_snapshot_family_surface.get('selector_count'))}`"
        ),
        (
            "- `stat_snapshot_family.covered_selector_count = "
            f"{_fmt(stat_snapshot_family_surface.get('covered_selector_count'))}`"
        ),
        (
            "- `stat_snapshot_family.report_path = "
            f"{_fmt(stat_snapshot_family_surface.get('report_path'))}`"
        ),
        (
            "- `stat_snapshot_family.current_mainline_status_path = "
            f"{_fmt(stat_snapshot_family_surface.get('current_mainline_status_path'))}`"
        ),
        (
            "- `stat_snapshot_family.summary_md_path = "
            f"{_fmt(stat_snapshot_family_surface.get('summary_md_path'))}`"
        ),
        (
            "- `stat_snapshot_family.load_error = "
            f"{_fmt(stat_snapshot_family_surface.get('load_error'))}`"
        ),
        "",
        "## Optional Freshness",
        f"- `queue.latest_date = {_fmt(queue_observer_surface.get('latest_date'))}`",
        f"- `queue.entry_count = {_fmt(queue_observer_surface.get('entry_count'))}`",
        f"- `queue.all_dates_ok = {_fmt(queue_observer_surface.get('all_dates_ok'))}`",
        f"- `queue.history_contract = {_fmt(queue_observer_surface.get('history_contract'))}`",
        f"- `queue.freshness_mode = {_fmt(queue_observer_surface.get('freshness_mode'))}`",
        f"- `queue.effective_entry_count = {_fmt(queue_observer_surface.get('effective_entry_count'))}`",
        f"- `queue.effective_all_dates_ok = {_fmt(queue_observer_surface.get('effective_all_dates_ok'))}`",
        f"- `primary_optional_group = {_fmt(primary_optional_group)}`",
        f"- `active_optional_group = {_fmt(active_optional_group)}`",
        f"- `active_optional_latest_date = {_fmt(primary_optional_rollup.get('latest_date'))}`",
        f"- `active_optional_history_contract = {_fmt(primary_optional_rollup.get('history_contract'))}`",
        f"- `active_optional_freshness_mode = {_fmt(primary_optional_rollup.get('freshness_mode'))}`",
        f"- `active_optional_effective_entry_count = {_fmt(primary_optional_rollup.get('effective_entry_count'))}`",
        f"- `active_optional_effective_all_dates_ok = {_fmt(primary_optional_rollup.get('effective_all_dates_ok'))}`",
        *optional_freshness_lines,
        "",
        "## Optional Admission",
        f"- `primary_optional_group = {_fmt(primary_optional_group)}`",
        f"- `active_optional_group = {_fmt(active_optional_group)}`",
        f"- `promotion_ready = {_fmt(primary_optional_admission.get('promotion_ready'))}`",
        f"- `explicit_review_ok = {_fmt(primary_optional_admission.get('explicit_review_ok'))}`",
        f"- `blocking = {_fmt(primary_optional_admission.get('blocking'))}`",
        *optional_admission_lines,
        "",
        "## Optional Failure Summary",
        *optional_failure_lines,
        "",
        "## Runtime Gate Semantics",
        (
            "- `completion_consumed_covers_visible`: "
            f"`{_fmt(completion_consume_check.get('summary'))}`"
        ),
    ]
    for family, signature in accepted_fault_rows:
        lines.append(f"- `{family}`: `{signature}`")
    for row in list(stat_snapshot_family_surface.get("selector_rows") or []):
        lines.append(
            "- `stat_snapshot_family.{name}.reference_ready = {ready}`".format(
                name=row.get("selector_name"),
                ready=_fmt(row.get("reference_ready")),
            )
        )
    lines.extend(
        [
            "",
            "## Refresh",
            "```bash",
            f"cd \"{lab_root}\"",
            f"python3 \"{lab_root / 'tools' / 'riscv_snn_lab.py'}\" export-mainline-status",
            f"python3 \"{lab_root / 'tools' / 'riscv_snn_lab.py'}\" mainline-refresh --group {_fmt(mainline_refresh_default_group)}",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def export_mainline_status(*,
                           sidecar_path: Path | None = None,
                           output_path: Path | None = None,
                           lab_root: Path = LAB_ROOT) -> Path:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    resolved_output_path = output_path or stable_markdown_path("current-mainline-status", lab_root=lab_root)
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    observer_summary_path = Path(
        sidecar_report.get("observer_summary_path")
        or stable_reference_path("nightly-sidecar-observer-summary", lab_root=lab_root)
    )
    research_report_path = Path(
        sidecar_report.get("research_report_path")
        or stable_reference_path("riscv-snn-research-report", lab_root=lab_root)
    )
    validation_report_path = Path(
        sidecar_report.get("observer_adequacy_validation_path")
        or stable_reference_path("observer-adequacy-validation", lab_root=lab_root)
    )
    runtime_gate_authority_path = _resolve_authority_path(lab_root=lab_root, default_path=RUNTIME_GATE_AUTHORITY_PATH)

    observer_summary = _load_json(observer_summary_path) if observer_summary_path.exists() else None
    research_report = _load_json(research_report_path) if research_report_path.exists() else None
    validation_report = _load_json(validation_report_path) if validation_report_path.exists() else None
    runtime_gate_authority = load_runtime_gate_authority(lab_root=lab_root)
    optional_group_names = sorted(_mainline_optional_groups(lab_root=lab_root))
    optional_group_rollups = _observer_summary_optional_group_rollups(observer_summary)
    optional_admission_paths: dict[str, Path] = {}
    optional_admission_surfaces: dict[str, dict[str, Any]] = {}
    for group in optional_group_names:
        audit_path = _latest_dated_reference(f"*-{group.replace('_', '-')}-admission-audit.json", lab_root=lab_root)
        if audit_path is None or not audit_path.exists():
            continue
        optional_admission_paths[group] = audit_path
        optional_admission_surfaces[group] = _load_json(audit_path)

    _atomic_write_text(
        resolved_output_path,
        render_mainline_status_markdown(
            sidecar_report,
            sidecar_path=resolved_sidecar_path,
            observer_summary=observer_summary,
            observer_summary_path=observer_summary_path if observer_summary is not None else None,
            research_report=research_report,
            research_report_path=research_report_path if research_report is not None else None,
            validation_report=validation_report,
            validation_report_path=validation_report_path if validation_report is not None else None,
            optional_group_names=optional_group_names,
            optional_group_rollups=optional_group_rollups,
            optional_admission_surfaces=optional_admission_surfaces,
            optional_admission_paths=optional_admission_paths,
            runtime_gate_authority=runtime_gate_authority,
            runtime_gate_authority_path=runtime_gate_authority_path,
        ),
    )
    return resolved_output_path


def _refresh_current_mainline_status(*,
                                     sidecar_path: Path | None = None,
                                     sidecar_report: dict[str, Any] | None = None,
                                     persist_to_sidecar: bool = False,
                                     lab_root: Path = LAB_ROOT) -> Path | None:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    resolved_sidecar_report = sidecar_report
    if resolved_sidecar_report is None:
        if not resolved_sidecar_path.exists():
            return None
        resolved_sidecar_report = _load_json(resolved_sidecar_path)
    if dict(resolved_sidecar_report or {}).get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        return None
    output_path = export_mainline_status(
        sidecar_path=resolved_sidecar_path,
        lab_root=lab_root,
    )
    if persist_to_sidecar:
        refreshed_sidecar_report = dict(resolved_sidecar_report)
        refreshed_sidecar_report["current_mainline_status_path"] = str(output_path)
        _write_json(resolved_sidecar_path, refreshed_sidecar_report)
    return output_path


def _refresh_stable_surface_refresh(*,
                                    sidecar_path: Path,
                                    sidecar_report: dict[str, Any],
                                    observer_summary_path: Path | None = None,
                                    current_mainline_status_path: Path | None = None,
                                    research_report_path: Path | None = None,
                                    observer_adequacy_validation_path: Path | None = None,
                                    supplementary_surface_history_path: Path | None = None,
                                    stable_surface_refresh_audit_path: Path | None = None,
                                    optional_promotion_dossier_path: Path | None = None) -> dict[str, Any]:
    refreshed_report = dict(sidecar_report)
    stable_surface_refresh = dict(refreshed_report.get("stable_surface_refresh") or {})
    stable_surface_refresh["refreshed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if observer_summary_path is not None:
        stable_surface_refresh["observer_summary_path"] = str(observer_summary_path)
    elif refreshed_report.get("observer_summary_path"):
        stable_surface_refresh.setdefault("observer_summary_path", str(refreshed_report.get("observer_summary_path")))
    if current_mainline_status_path is not None:
        stable_surface_refresh["current_mainline_status_path"] = str(current_mainline_status_path)
    elif refreshed_report.get("current_mainline_status_path"):
        stable_surface_refresh.setdefault(
            "current_mainline_status_path",
            str(refreshed_report.get("current_mainline_status_path")),
        )
    if research_report_path is not None:
        stable_surface_refresh["research_report_path"] = str(research_report_path)
    elif refreshed_report.get("research_report_path"):
        stable_surface_refresh.setdefault("research_report_path", str(refreshed_report.get("research_report_path")))
    if observer_adequacy_validation_path is not None:
        stable_surface_refresh["observer_adequacy_validation_path"] = str(observer_adequacy_validation_path)
    elif refreshed_report.get("observer_adequacy_validation_path"):
        stable_surface_refresh.setdefault(
            "observer_adequacy_validation_path",
            str(refreshed_report.get("observer_adequacy_validation_path")),
        )
    if supplementary_surface_history_path is not None:
        stable_surface_refresh["supplementary_surface_history_path"] = str(supplementary_surface_history_path)
    elif refreshed_report.get("supplementary_surface_history_path"):
        stable_surface_refresh.setdefault(
            "supplementary_surface_history_path",
            str(refreshed_report.get("supplementary_surface_history_path")),
        )
    if stable_surface_refresh_audit_path is not None:
        stable_surface_refresh["stable_surface_refresh_audit_path"] = str(stable_surface_refresh_audit_path)
    elif refreshed_report.get("stable_surface_refresh_audit_path"):
        stable_surface_refresh.setdefault(
            "stable_surface_refresh_audit_path",
            str(refreshed_report.get("stable_surface_refresh_audit_path")),
        )
    if optional_promotion_dossier_path is not None:
        stable_surface_refresh["optional_promotion_dossier_path"] = str(optional_promotion_dossier_path)
    elif refreshed_report.get("stable_surface_refresh", {}).get("optional_promotion_dossier_path"):
        stable_surface_refresh.setdefault(
            "optional_promotion_dossier_path",
            str(refreshed_report.get("stable_surface_refresh", {}).get("optional_promotion_dossier_path")),
        )
    refreshed_report["stable_surface_refresh"] = stable_surface_refresh
    if current_mainline_status_path is not None:
        refreshed_report["current_mainline_status_path"] = str(current_mainline_status_path)
    if supplementary_surface_history_path is not None:
        refreshed_report["supplementary_surface_history_path"] = str(supplementary_surface_history_path)
    if stable_surface_refresh_audit_path is not None:
        refreshed_report["stable_surface_refresh_audit_path"] = str(stable_surface_refresh_audit_path)
    _write_json(sidecar_path, refreshed_report)
    return refreshed_report


def _resolve_derived_surface_paths(*,
                                   sidecar_path: Path,
                                   sidecar_report: dict[str, Any],
                                   observer_summary_path: Path | None = None,
                                   lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    return {
        "observer_summary_path": observer_summary_path or Path(
            sidecar_report.get("observer_summary_path")
            or stable_reference_path("nightly-sidecar-observer-summary", lab_root=lab_root)
        ),
        "research_report_path": Path(
            sidecar_report.get("research_report_path")
            or stable_reference_path("riscv-snn-research-report", lab_root=lab_root)
        ),
        "observer_adequacy_validation_path": Path(
            sidecar_report.get("observer_adequacy_validation_path")
            or stable_reference_path("observer-adequacy-validation", lab_root=lab_root)
        ),
        "current_mainline_status_path": Path(
            sidecar_report.get("current_mainline_status_path")
            or stable_markdown_path("current-mainline-status", lab_root=lab_root)
        ),
        "summary_md_path": Path(
            sidecar_report.get("summary_md_path")
            or stable_markdown_path("nightly-sidecar-summary", lab_root=lab_root)
        ),
        "supplementary_surface_history_path": Path(
            sidecar_report.get("supplementary_surface_history_path")
            or stable_reference_path("supplementary-surface-history", lab_root=lab_root)
        ),
        "stable_surface_refresh_audit_path": Path(
            sidecar_report.get("stable_surface_refresh_audit_path")
            or stable_reference_path("stable-surface-refresh-audit", lab_root=lab_root)
        ),
        "sidecar_path": sidecar_path,
    }


def _refresh_derived_stable_surfaces(*,
                                     sidecar_path: Path,
                                     observer_summary_path: Path | None = None,
                                     optional_promotion_dossier_path: Path | None = None,
                                     lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    sidecar_report = _load_json(sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{sidecar_path} is not a stable top-level gate artifact")
    refreshed_supplementary_report = _refresh_report_supplementary_surfaces(
        sidecar_report,
        lab_root=lab_root,
    )
    if refreshed_supplementary_report != sidecar_report:
        sidecar_report = refreshed_supplementary_report
        _write_json(sidecar_path, sidecar_report)

    surface_paths = _resolve_derived_surface_paths(
        sidecar_path=sidecar_path,
        sidecar_report=sidecar_report,
        observer_summary_path=observer_summary_path,
        lab_root=lab_root,
    )
    refresh_supplementary_surface_history(
        sidecar_report=sidecar_report,
        sidecar_path=sidecar_path,
        output_path=surface_paths["supplementary_surface_history_path"],
        lab_root=lab_root,
    )

    build_sidecar_observer_summary(
        sidecar_report,
        output_path=surface_paths["observer_summary_path"],
        lab_root=lab_root,
    )
    if (
        sidecar_report.get("observer_summary_path") != str(surface_paths["observer_summary_path"])
        or sidecar_report.get("summary_md_path") != str(surface_paths["summary_md_path"])
    ):
        sidecar_report = dict(sidecar_report)
        sidecar_report["observer_summary_path"] = str(surface_paths["observer_summary_path"])
        sidecar_report["summary_md_path"] = str(surface_paths["summary_md_path"])
        _write_json(sidecar_path, sidecar_report)

    research_outputs = run_research_postprocess(
        sidecar_path=sidecar_path,
        lab_root=lab_root,
    )
    refreshed_sidecar_report = _refresh_stable_surface_refresh(
        sidecar_path=sidecar_path,
        sidecar_report=_load_json(sidecar_path),
        observer_summary_path=surface_paths["observer_summary_path"],
        current_mainline_status_path=surface_paths["current_mainline_status_path"],
        research_report_path=research_outputs["research_report_path"],
        observer_adequacy_validation_path=research_outputs["observer_adequacy_validation_path"],
        supplementary_surface_history_path=surface_paths["supplementary_surface_history_path"],
        stable_surface_refresh_audit_path=surface_paths["stable_surface_refresh_audit_path"],
        optional_promotion_dossier_path=optional_promotion_dossier_path,
    )
    current_mainline_status_path = _refresh_current_mainline_status(
        sidecar_path=sidecar_path,
        sidecar_report=refreshed_sidecar_report,
        persist_to_sidecar=False,
        lab_root=lab_root,
    )
    if refreshed_sidecar_report.get("summary_md_path") != str(surface_paths["summary_md_path"]):
        refreshed_sidecar_report = dict(refreshed_sidecar_report)
        refreshed_sidecar_report["summary_md_path"] = str(surface_paths["summary_md_path"])
        _write_json(sidecar_path, refreshed_sidecar_report)
    build_sidecar_summary_md(
        refreshed_sidecar_report,
        output_path=surface_paths["summary_md_path"],
        lab_root=lab_root,
    )
    audit_stable_surface_refresh(
        sidecar_path=sidecar_path,
        output_path=surface_paths["stable_surface_refresh_audit_path"],
        lab_root=lab_root,
    )
    return {
        "observer_summary_path": surface_paths["observer_summary_path"],
        "research_report_path": research_outputs["research_report_path"],
        "observer_adequacy_validation_path": research_outputs["observer_adequacy_validation_path"],
        "current_mainline_status_path": current_mainline_status_path,
        "summary_md_path": surface_paths["summary_md_path"],
        "supplementary_surface_history_path": surface_paths["supplementary_surface_history_path"],
        "stable_surface_refresh_audit_path": surface_paths["stable_surface_refresh_audit_path"],
    }


def _audit_path_presence(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
    }


def audit_stable_surface_refresh(*,
                                 sidecar_path: Path | None = None,
                                 output_path: Path | None = None,
                                 lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    sidecar_report = _load_json(resolved_sidecar_path)
    if sidecar_report.get("artifact_role") != ARTIFACT_ROLE_STABLE_TOP_LEVEL_GATE:
        raise ValueError(f"{resolved_sidecar_path} is not a stable top-level gate artifact")

    surface_paths = _resolve_derived_surface_paths(
        sidecar_path=resolved_sidecar_path,
        sidecar_report=sidecar_report,
        lab_root=lab_root,
    )
    stable_surface_refresh = dict(sidecar_report.get("stable_surface_refresh") or {})
    checks: dict[str, dict[str, Any]] = {}
    observer_summary: dict[str, Any] | None = None
    current_mainline_text = ""
    summary_md_text = ""

    refresh_metadata_issues: list[str] = []
    for field in (
        "observer_summary_path",
        "research_report_path",
        "observer_adequacy_validation_path",
        "current_mainline_status_path",
        "supplementary_surface_history_path",
        "stable_surface_refresh_audit_path",
    ):
        expected = str(surface_paths[field])
        if sidecar_report.get(field) != expected:
            refresh_metadata_issues.append(f"sidecar.{field}")
        if stable_surface_refresh.get(field) != expected:
            refresh_metadata_issues.append(f"stable_surface_refresh.{field}")
    checks["sidecar_refresh_metadata"] = {
        "ok": not refresh_metadata_issues,
        "issues": refresh_metadata_issues,
        "sidecar_path": str(resolved_sidecar_path),
    }

    observer_summary_issues: list[str] = []
    observer_presence = _audit_path_presence(surface_paths["observer_summary_path"])
    if observer_presence["exists"]:
        observer_summary = _load_json(surface_paths["observer_summary_path"])
        if observer_summary.get("artifact_role") != ARTIFACT_ROLE_STABLE_SIDECAR_OBSERVER_SUMMARY:
            observer_summary_issues.append("artifact_role")
        authority_entrypoint = dict(observer_summary.get("authority_entrypoint") or {})
        if authority_entrypoint.get("summary_path") != str(resolved_sidecar_path):
            observer_summary_issues.append("authority_entrypoint.summary_path")
    checks["observer_summary"] = {
        **observer_presence,
        "ok": observer_presence["exists"] and not observer_summary_issues,
        "issues": observer_summary_issues,
    }

    research_issues: list[str] = []
    research_presence = _audit_path_presence(surface_paths["research_report_path"])
    if research_presence["exists"]:
        research_report = _load_json(surface_paths["research_report_path"])
        if research_report.get("artifact_role") != "research_metrics_summary":
            research_issues.append("artifact_role")
        observer_entrypoint = dict(research_report.get("observer_entrypoint") or {})
        if observer_entrypoint.get("summary_path") != str(surface_paths["observer_summary_path"]):
            research_issues.append("observer_entrypoint.summary_path")
    checks["research_report"] = {
        **research_presence,
        "ok": research_presence["exists"] and not research_issues,
        "issues": research_issues,
    }

    validation_issues: list[str] = []
    validation_presence = _audit_path_presence(surface_paths["observer_adequacy_validation_path"])
    if validation_presence["exists"]:
        validation_report = _load_json(surface_paths["observer_adequacy_validation_path"])
        if validation_report.get("artifact_role") != "observer_adequacy_validation_summary":
            validation_issues.append("artifact_role")
        source = dict(validation_report.get("source") or {})
        if source.get("path") != str(surface_paths["research_report_path"]):
            validation_issues.append("source.path")
        observer_entrypoint = dict(validation_report.get("observer_entrypoint") or {})
        if observer_entrypoint.get("summary_path") != str(surface_paths["observer_summary_path"]):
            validation_issues.append("observer_entrypoint.summary_path")
    checks["observer_adequacy_validation"] = {
        **validation_presence,
        "ok": validation_presence["exists"] and not validation_issues,
        "issues": validation_issues,
    }

    current_mainline_issues: list[str] = []
    current_mainline_presence = _audit_path_presence(surface_paths["current_mainline_status_path"])
    if current_mainline_presence["exists"]:
        current_mainline_text = surface_paths["current_mainline_status_path"].read_text(encoding="utf-8")
        required_markers = (
            str(resolved_sidecar_path),
            str(surface_paths["observer_summary_path"]),
            str(surface_paths["research_report_path"]),
            str(surface_paths["observer_adequacy_validation_path"]),
        )
        for marker in required_markers:
            if marker not in current_mainline_text:
                current_mainline_issues.append(f"missing:{marker}")
    checks["current_mainline_status"] = {
        **current_mainline_presence,
        "ok": current_mainline_presence["exists"] and not current_mainline_issues,
        "issues": current_mainline_issues,
    }

    summary_md_issues: list[str] = []
    summary_md_presence = _audit_path_presence(surface_paths["summary_md_path"])
    if summary_md_presence["exists"]:
        summary_md_text = surface_paths["summary_md_path"].read_text(encoding="utf-8")
        for marker in (str(resolved_sidecar_path), str(surface_paths["observer_summary_path"])):
            if marker not in summary_md_text:
                summary_md_issues.append(f"missing:{marker}")
    checks["sidecar_summary_md"] = {
        **summary_md_presence,
        "ok": summary_md_presence["exists"] and not summary_md_issues,
        "issues": summary_md_issues,
    }

    supplementary_surfaces = _report_supplementary_surfaces(sidecar_report, lab_root=lab_root)
    observer_supplementary_surfaces = {
        name: _normalize_supplementary_surface(name, payload, lab_root=lab_root)
        for name, payload in dict((observer_summary or {}).get("supplementary_surfaces") or {}).items()
        if isinstance(payload, dict)
    }
    observer_supplementary_rollups = {
        str(name): dict(payload or {})
        for name, payload in dict((observer_summary or {}).get("supplementary_surface_rollups") or {}).items()
        if isinstance(payload, dict)
    }
    for name, surface in supplementary_surfaces.items():
        issues: list[str] = []
        issues.extend(_supplementary_surface_contract_issues(name, surface, lab_root=lab_root))
        expected_rollup = _supplementary_surface_rollup(name, surface, lab_root=lab_root)
        observer_surface = observer_supplementary_surfaces.get(name)
        if observer_surface is None:
            issues.append("observer_summary.surface_missing")
        else:
            for field in (
                "present",
                "blocking",
                "load_error",
                "gate_ok",
                "stale",
                "freshness_mode",
                "effective_all_dates_ok",
                "report_path",
                "current_mainline_status_path",
                "summary_md_path",
            ):
                if observer_surface.get(field) != surface.get(field):
                    issues.append(f"observer_summary.{field}")
        observed_rollup = observer_supplementary_rollups.get(name)
        if observed_rollup is None:
            issues.append("observer_summary.rollup_missing")
        else:
            for field in (
                "status",
                "blocking",
                "healthy",
                "freshness_ok",
                "load_error",
            ):
                if observed_rollup.get(field) != expected_rollup.get(field):
                    issues.append(f"observer_summary.rollup.{field}")
        for field in ("report_path", "current_mainline_status_path", "summary_md_path"):
            path_value = surface.get(field)
            if not path_value:
                issues.append(f"missing_field:{field}")
                continue
            if not Path(str(path_value)).exists():
                issues.append(f"missing_path:{field}")
        checks[f"supplementary_surfaces.{name}"] = {
            "ok": not issues,
            "issues": issues,
            "status": expected_rollup.get("status"),
            "blocking": expected_rollup.get("blocking"),
            "path": surface.get("report_path"),
        }

        chain_issues: list[str] = []
        report_marker = surface.get("report_path")
        current_marker = surface.get("current_mainline_status_path")
        if current_mainline_presence["exists"]:
            if report_marker and str(report_marker) not in current_mainline_text:
                chain_issues.append("current_mainline.report_path")
            if current_marker and str(current_marker) not in current_mainline_text:
                chain_issues.append("current_mainline.current_mainline_status_path")
        else:
            chain_issues.append("current_mainline.missing")
        if summary_md_presence["exists"]:
            if report_marker and str(report_marker) not in summary_md_text:
                chain_issues.append("summary_md.report_path")
            if current_marker and str(current_marker) not in summary_md_text:
                chain_issues.append("summary_md.current_mainline_status_path")
        else:
            chain_issues.append("summary_md.missing")
        checks[f"supplementary_surfaces.{name}_chain"] = {
            "ok": not chain_issues,
            "issues": chain_issues,
            "path": surface.get("report_path"),
        }

    optional_group_surfaces = _report_optional_group_surfaces(sidecar_report)
    observer_optional_group_rollups = {
        str(name): dict(payload or {})
        for name, payload in dict((observer_summary or {}).get("optional_group_rollups") or {}).items()
        if isinstance(payload, dict)
    }
    optional_groups = sorted(set(optional_group_surfaces.keys()) | set(observer_optional_group_rollups.keys()))
    for group in optional_groups:
        live_surface = dict(optional_group_surfaces.get(group) or {})
        observed_rollup = dict(observer_optional_group_rollups.get(group) or {})
        issues: list[str] = []
        if not observed_rollup:
            issues.append("observer_summary.rollup_missing")
        else:
            live_surface_label = None
            if "surface" in live_surface:
                live_surface_label = live_surface.get("surface")
            elif live_surface.get("canonical_surface") is not None:
                live_surface_label = _surface_label(live_surface.get("canonical_surface"))
            if live_surface.get("summary_path") is not None and (
                observed_rollup.get("summary_path") != live_surface.get("summary_path")
            ):
                issues.append("observer_summary.summary_path")
            if live_surface.get("count") is not None and observed_rollup.get("count") != live_surface.get("count"):
                issues.append("observer_summary.count")
            if live_surface.get("all_ok") is not None and observed_rollup.get("all_ok") != live_surface.get("all_ok"):
                issues.append("observer_summary.all_ok")
            if live_surface_label is not None and observed_rollup.get("surface") != live_surface_label:
                issues.append("observer_summary.surface")
            for field in ("freshness_mode", "effective_entry_count", "effective_all_dates_ok"):
                if observed_rollup.get(field) is None:
                    issues.append(f"observer_summary.missing_{field}")
        checks[f"optional_group_rollups.{group}"] = {
            "ok": not issues,
            "issues": issues,
            "summary_path": live_surface.get("summary_path"),
            "group": group,
        }

    observer_optional_surfaces = dict((observer_summary or {}).get("optional_surfaces") or {})
    queue_optional_surface = dict(observer_optional_surfaces.get("queue_equivalence") or {})
    queue_optional_rollup = dict(observer_optional_group_rollups.get("queue_optional") or {})
    if queue_optional_surface or queue_optional_rollup:
        queue_issues: list[str] = []
        if not queue_optional_surface:
            queue_issues.append("observer_summary.optional_surfaces.queue_equivalence_missing")
        if not queue_optional_rollup:
            queue_issues.append("observer_summary.optional_group_rollups.queue_optional_missing")
        for field in ("freshness_mode", "effective_entry_count", "effective_all_dates_ok", "history_path"):
            if queue_optional_surface.get(field) != queue_optional_rollup.get(field):
                queue_issues.append(f"observer_summary.queue_equivalence.{field}")
        checks["optional_surfaces.queue_equivalence_chain"] = {
            "ok": not queue_issues,
            "issues": queue_issues,
            "summary_path": queue_optional_rollup.get("summary_path") or queue_optional_surface.get("summary_path"),
        }

    all_ok = all(bool(row.get("ok")) for row in checks.values())
    resolved_output_path = output_path or stable_reference_path("stable-surface-refresh-audit", lab_root=lab_root)
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_STABLE_SURFACE_REFRESH_AUDIT,
            scope="derived_surface_consistency_observer",
            producer="riscv_snn_lab.audit_stable_surface_refresh",
        ),
        "sidecar_path": str(resolved_sidecar_path),
        "observer_summary_path": str(surface_paths["observer_summary_path"]),
        "research_report_path": str(surface_paths["research_report_path"]),
        "observer_adequacy_validation_path": str(surface_paths["observer_adequacy_validation_path"]),
        "current_mainline_status_path": str(surface_paths["current_mainline_status_path"]),
        "summary_md_path": str(surface_paths["summary_md_path"]),
        "refreshed_at_utc": stable_surface_refresh.get("refreshed_utc"),
        "optional_promotion_dossier_path": stable_surface_refresh.get("optional_promotion_dossier_path"),
        "all_ok": all_ok,
        "checks": checks,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, summary)
    return summary


def export_optional_promotion_dossier(*,
                                      group: str = "queue_optional",
                                      output_path: Path | None = None,
                                      lab_root: Path = LAB_ROOT) -> Path:
    admission = run_family_admission_audit(group=group, lab_root=lab_root)
    resolved_output_path = output_path or default_reference_path(
        f"{group.replace('_', '-')}-promotion-dossier",
        lab_root=lab_root,
    )
    payload = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_OPTIONAL_PROMOTION_DOSSIER,
            scope="research_only_nonblocking",
            producer="riscv_snn_lab.export_optional_promotion_dossier",
        ),
        "contract_primary": OPTIONAL_PROMOTION_DOSSIER_PRIMARY_CONTRACT,
        "group": group,
        "families": admission.get("families", []),
        "blocking": admission.get("blocking"),
        "promotion_ready": admission.get("promotion_ready"),
        "admission": {
            "summary_path": admission.get("summary_path"),
            "contract_primary": admission.get("contract_primary") or OPTIONAL_ADMISSION_PRIMARY_CONTRACT,
            "primary_contract_fields": list(
                admission.get("primary_contract_fields") or OPTIONAL_ADMISSION_PRIMARY_FIELDS
            ),
            "compatibility_aliases": dict(admission.get("compatibility_aliases") or {}),
            "group": admission.get("group"),
            "blocking": admission.get("blocking"),
            "promotion_ready": admission.get("promotion_ready"),
            "group_equivalence_path": admission.get("group_equivalence_path"),
            "group_equivalence_all_ok": admission.get("group_equivalence_all_ok"),
            "group_history_path": admission.get("group_history_path"),
            "group_history_entry_count": admission.get("group_history_entry_count"),
            "group_history_all_dates_ok": admission.get("group_history_all_dates_ok"),
            "group_history_latest_recovered_date": admission.get("group_history_latest_recovered_date"),
            "group_history_freshness_mode": admission.get("group_history_freshness_mode"),
            "group_history_effective_entry_count": admission.get("group_history_effective_entry_count"),
            "group_history_effective_all_dates_ok": admission.get("group_history_effective_all_dates_ok"),
            "explicit_review_ok": admission.get("explicit_review_ok"),
            "explicit_review_path": admission.get("explicit_review_path"),
            "explicit_review_decision": admission.get("explicit_review_decision"),
            "explicit_review_reviewer": admission.get("explicit_review_reviewer"),
            "explicit_review_date": admission.get("explicit_review_date"),
        },
        "evidence": {
            "equivalence_summary_path": admission.get("group_equivalence_path"),
            "history_path": admission.get("group_history_path"),
            "history_entry_count": admission.get("group_history_entry_count"),
            "history_all_dates_ok": admission.get("group_history_all_dates_ok"),
            "history_latest_recovered_date": admission.get("group_history_latest_recovered_date"),
            "history_freshness_mode": admission.get("group_history_freshness_mode"),
            "history_effective_entry_count": admission.get("group_history_effective_entry_count"),
            "history_effective_all_dates_ok": admission.get("group_history_effective_all_dates_ok"),
            "explicit_review_ok": admission.get("explicit_review_ok"),
            "explicit_review_path": admission.get("explicit_review_path"),
            "required_contracts": admission.get("required_contracts"),
            "stable_sidecar_path": admission.get("stable_sidecar_path"),
            "stable_history_path": admission.get("stable_history_path"),
            "stable_history_latest_date": admission.get("stable_history_latest_date"),
        },
    }
    _write_json(resolved_output_path, payload)
    return resolved_output_path


def export_family_promotion_dossier(*,
                                    group: str = "queue_optional",
                                    output_path: Path | None = None,
                                    lab_root: Path = LAB_ROOT) -> Path:
    return export_optional_promotion_dossier(
        group=group,
        output_path=output_path,
        lab_root=lab_root,
    )


def _refresh_optional_admission_surfaces(*,
                                         selected_group: str | None = None,
                                         lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    refreshed_paths: dict[str, Path] = {}
    for group in sorted(_mainline_optional_groups(lab_root=lab_root)):
        if selected_group is not None and group == selected_group:
            continue
        summary = run_family_admission_audit(group=group, lab_root=lab_root)
        summary_path = summary.get("summary_path")
        if summary_path:
            refreshed_paths[group] = Path(str(summary_path))
    return refreshed_paths


def refresh_mainline_surfaces(*,
                              sample_paths: list[Path] | None = None,
                              group: str = "completion_overflow_optional",
                              compact_observer_history_since_latest_recovery: bool = False,
                              sidecar_path: Path | None = None,
                              observer_summary_path: Path | None = None,
                              dossier_output_path: Path | None = None,
                              lab_root: Path = LAB_ROOT) -> dict[str, Path]:
    resolved_sidecar_path = sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root)
    if not resolved_sidecar_path.exists():
        raise FileNotFoundError(f"stable sidecar report missing: {resolved_sidecar_path}")

    optional_admission_paths = _refresh_optional_admission_surfaces(
        selected_group=group,
        lab_root=lab_root,
    )
    dossier_path = export_family_promotion_dossier(
        group=group,
        output_path=dossier_output_path,
        lab_root=lab_root,
    )
    _, selected_admission_path = _latest_optional_admission_audit(
        group=group,
        lab_root=lab_root,
    )
    if selected_admission_path is not None:
        optional_admission_paths[group] = selected_admission_path
    refreshed = refresh_observer_surfaces(
        sample_paths=sample_paths,
        compact_observer_history_since_latest_recovery=compact_observer_history_since_latest_recovery,
        sidecar_path=sidecar_path,
        observer_summary_path=observer_summary_path,
        optional_promotion_dossier_path=dossier_path,
        lab_root=lab_root,
    )
    return {
        **refreshed,
        "optional_promotion_dossier_path": dossier_path,
        "optional_admission_paths": optional_admission_paths,
    }


def run_observer_fail_recovery_loop(*,
                                    group: str | None = None,
                                    sample_paths: list[Path] | None = None,
                                    sidecar_path: Path | None = None,
                                    observer_summary_path: Path | None = None,
                                    dossier_output_path: Path | None = None,
                                    optional_history_output_path: Path | None = None,
                                    stable_surface_audit_output_path: Path | None = None,
                                    output_path: Path | None = None,
                                    lab_root: Path = LAB_ROOT) -> dict[str, Any]:
    refresh_group = group or _mainline_refresh_default_group(lab_root=lab_root)
    if refresh_group is None:
        raise ValueError("observer-fail-recovery requires at least one optional group in authority")
    expected_refresh_mode = _optional_history_refresh_mode(refresh_group, lab_root=lab_root)
    compact_since_latest_recovery = expected_refresh_mode == "compact_latest_recovery"
    optional_history = refresh_optional_equivalence_history(
        group=refresh_group,
        sample_paths=sample_paths,
        compact_since_latest_recovery=compact_since_latest_recovery,
        output_path=optional_history_output_path,
        lab_root=lab_root,
    )
    refreshed = refresh_mainline_surfaces(
        sample_paths=sample_paths,
        group=refresh_group,
        compact_observer_history_since_latest_recovery=compact_since_latest_recovery,
        sidecar_path=sidecar_path,
        observer_summary_path=observer_summary_path,
        dossier_output_path=dossier_output_path,
        lab_root=lab_root,
    )
    resolved_sidecar_path = (
        Path(str(refreshed["sidecar_path"]))
        if "sidecar_path" in refreshed
        else (sidecar_path or stable_reference_path("nightly-sidecar-report", lab_root=lab_root))
    )
    stable_surface_audit = audit_stable_surface_refresh(
        sidecar_path=resolved_sidecar_path,
        output_path=stable_surface_audit_output_path,
        lab_root=lab_root,
    )
    observer_history_path = refreshed.get("observer_history_path")
    observer_history = {}
    if observer_history_path:
        resolved_observer_history_path = Path(str(observer_history_path))
        if resolved_observer_history_path.exists():
            observer_history = _load_json(resolved_observer_history_path)
    effective_all_dates_ok = optional_history.get("effective_all_dates_ok")
    if effective_all_dates_ok is None:
        effective_all_dates_ok = optional_history.get("all_dates_ok")
    observer_effective_all_dates_ok = observer_history.get("effective_all_dates_ok")
    if observer_effective_all_dates_ok is None:
        observer_effective_all_dates_ok = observer_history.get("all_dates_ok")
    summary_all_ok = bool(stable_surface_audit.get("all_ok")) and bool(effective_all_dates_ok)
    resolved_output_path = output_path or stable_reference_path(
        "observer-fail-recovery-loop-summary",
        lab_root=lab_root,
    )
    summary = {
        **_artifact_metadata(
            role=ARTIFACT_ROLE_OBSERVER_FAIL_RECOVERY_LOOP,
            scope="observer_fail_recovery_loop_only",
            producer="riscv_snn_lab.run_observer_fail_recovery_loop",
        ),
        "group": refresh_group,
        "sample_count": len(sample_paths or []),
        "group_history_refresh_mode_expected": expected_refresh_mode,
        "group_history_refresh_mode": optional_history.get("refresh_mode"),
        "group_history_latest_recovered_date": optional_history.get("latest_recovered_date"),
        "group_history_effective_entry_count": (
            optional_history.get("effective_entry_count")
            if optional_history.get("effective_entry_count") is not None
            else optional_history.get("entry_count")
        ),
        "group_history_effective_all_dates_ok": effective_all_dates_ok,
        "optional_history_summary_path": optional_history.get("summary_path"),
        "observer_history_path": str(refreshed.get("observer_history_path", "")),
        "observer_history_refresh_mode": observer_history.get("refresh_mode"),
        "observer_history_latest_recovered_date": observer_history.get("latest_recovered_date"),
        "observer_history_effective_entry_count": (
            observer_history.get("effective_entry_count")
            if observer_history.get("effective_entry_count") is not None
            else observer_history.get("entry_count")
        ),
        "observer_history_effective_all_dates_ok": observer_effective_all_dates_ok,
        "observer_summary_path": str(refreshed.get("observer_summary_path", "")),
        "current_mainline_status_path": str(refreshed.get("current_mainline_status_path", "")),
        "optional_promotion_dossier_path": str(refreshed.get("optional_promotion_dossier_path", "")),
        "stable_surface_refresh_audit_path": stable_surface_audit.get("summary_path"),
        "audit_all_ok": bool(stable_surface_audit.get("all_ok")),
        "all_ok": summary_all_ok,
        "summary_path": str(resolved_output_path),
    }
    _write_json(resolved_output_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="riscv_snn_lab.py",
        description="Thin orchestration wrapper for the experimental riscv_snn ISA lab",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List sample firmware programs")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable sample manifest JSON")

    gen_parser = subparsers.add_parser("generate", help="Generate lab-local firmware/spec assets for a sample")
    gen_parser.add_argument("--program", required=True, help="Sample firmware program")
    gen_parser.add_argument("--elf", default="", help="Override output ELF path")
    gen_parser.add_argument("--spec", default="", help="Override output spec path")

    validate_parser = subparsers.add_parser("validate", help="Validate a lab-local replay spec")
    validate_group = validate_parser.add_mutually_exclusive_group(required=True)
    validate_group.add_argument("--program", help="Resolve the default lab-local spec path from a sample program")
    validate_group.add_argument("--spec", help="Validate an explicit spec path")

    smoke_parser = subparsers.add_parser("smoke", help="Generate/validate/run a lab-local smoke spec")
    smoke_group = smoke_parser.add_mutually_exclusive_group(required=True)
    smoke_group.add_argument("--program", help="Generate the default lab-local assets, validate them, then smoke")
    smoke_group.add_argument("--spec", help="Smoke an existing spec path after validation")

    preflight_parser = subparsers.add_parser(
        "runtime-bridge-preflight",
        help="Check whether runtime_bridge consumer objects are fresh enough before smoke/equiv/sidecar runs",
    )
    preflight_group = preflight_parser.add_mutually_exclusive_group(required=True)
    preflight_group.add_argument(
        "--program",
        help="Resolve the lab-local default spec for one program before checking runtime_bridge build freshness",
    )
    preflight_group.add_argument(
        "--spec",
        help="Check one existing spec path without running SST",
    )

    protocol_parser = subparsers.add_parser(
        "protocol",
        help="Run the explicit experimental protocol harness targets without touching the default check flow",
    )
    protocol_parser.add_argument(
        "--suite",
        choices=("all", "builder", "toolchain"),
        default="all",
        help="Select which protocol harness suite to run",
    )

    regress_parser = subparsers.add_parser(
        "regress",
        help="Run explicit experimental protocol harnesses first, then execute one smoke program",
    )
    regress_parser.add_argument("--program", required=True, help="Sample firmware program to smoke after protocol")
    regress_parser.add_argument(
        "--suite",
        choices=("all", "builder", "toolchain"),
        default="all",
        help="Select which protocol harness suite to run before smoke",
    )
    regress_parser.add_argument(
        "--register",
        action="store_true",
        help="After smoke completes, also write a manifest draft into the lab runs directory",
    )
    regress_parser.add_argument(
        "--manifest",
        default="",
        help="Override manifest output path when --register is enabled",
    )

    matrix_parser = subparsers.add_parser(
        "matrix",
        help="Run the explicit experimental regression matrix and persist a JSON summary under references/",
    )
    matrix_parser.add_argument(
        "--group",
        choices=("all", "builder", "toolchain"),
        default="all",
        help="Select which explicit regression surface to execute",
    )
    matrix_parser.add_argument(
        "--register",
        action="store_true",
        help="Also register each smoke run as a manifest draft under the lab runs directory",
    )
    matrix_parser.add_argument(
        "--summary",
        default="",
        help="Override the JSON summary output path",
    )

    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit builder/toolchain bridge assets against the latest registered manifest without creating a new authority",
    )
    audit_parser.add_argument(
        "--group",
        choices=("all", "builder", "toolchain"),
        default="toolchain",
        help="Select which explicit asset surface to audit",
    )
    audit_parser.add_argument(
        "--protocol",
        action="store_true",
        help="Run the explicit protocol harness suite before collecting the drift audit summary",
    )
    audit_parser.add_argument(
        "--summary",
        default="",
        help="Override the JSON summary output path",
    )

    equiv_parser = subparsers.add_parser(
        "equiv",
        help="Run the fixed snn vs riscv_snn(runtime_bridge) compare surface for one family",
    )
    equiv_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        required=True,
        help="Equivalence family to run",
    )
    equiv_parser.add_argument(
        "--summary",
        default="",
        help="Override the JSON summary output path",
    )

    equiv_matrix_parser = subparsers.add_parser(
        "equiv-matrix",
        help="Run the dated equivalence freshness matrix across one or more frozen families without creating a new authority",
    )
    equiv_matrix_parser.add_argument(
        "--group",
        choices=_equiv_matrix_group_names(),
        default="all",
        help="Select a frozen equivalence family preset when no explicit --family is provided",
    )
    equiv_matrix_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        action="append",
        default=[],
        help="Restrict the run to one or more explicit equivalence families; repeat to build a smaller matrix",
    )
    equiv_matrix_parser.add_argument(
        "--summary",
        default="",
        help="Override the top-level equivalence matrix summary output path",
    )

    reference_compare_parser = subparsers.add_parser(
        "reference-compare",
        help="Run one reference-model vs runtime compare surface for a frozen family without changing top-level gate authority",
    )
    reference_compare_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        required=True,
        help="Equivalence family to compare through the reference model surface",
    )
    reference_compare_parser.add_argument(
        "--summary",
        default="",
        help="Override the family reference-compare summary output path",
    )

    reference_compare_matrix_parser = subparsers.add_parser(
        "reference-compare-matrix",
        help="Run the non-blocking reference-compare matrix across one or more frozen families",
    )
    reference_compare_matrix_parser.add_argument(
        "--group",
        choices=_equiv_matrix_group_names(),
        default="all",
        help="Select a frozen equivalence family preset when no explicit --family is provided",
    )
    reference_compare_matrix_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        action="append",
        default=[],
        help="Restrict the run to one or more explicit equivalence families; repeat to build a smaller matrix",
    )
    reference_compare_matrix_parser.add_argument(
        "--summary",
        default="",
        help="Override the reference-compare matrix output path",
    )

    reference_compare_refresh_parser = subparsers.add_parser(
        "reference-compare-refresh",
        help="Refresh the stable non-blocking reference-compare supplementary surface and derived observer/current-state views",
    )
    reference_compare_refresh_parser.add_argument(
        "--group",
        choices=_equiv_matrix_group_names(),
        default="all",
        help="Frozen family preset to refresh into the stable reference_compare surface",
    )
    reference_compare_refresh_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        action="append",
        default=[],
        help="Restrict the refresh to one or more explicit families; repeat to build a smaller matrix",
    )
    reference_compare_refresh_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )

    reference_program_compare_parser = subparsers.add_parser(
        "reference-program-compare",
        help="Run one program-level reference-model vs runtime compare surface for a frozen family without changing top-level gate authority",
    )
    reference_program_compare_parser.add_argument(
        "--family",
        choices=_reference_program_compare_family_names(),
        required=True,
        help="Frozen program-semantics family to compare through the reference program model surface",
    )
    reference_program_compare_parser.add_argument(
        "--summary",
        default="",
        help="Override the family reference-program-compare summary output path",
    )

    reference_program_compare_matrix_parser = subparsers.add_parser(
        "reference-program-compare-matrix",
        help="Run the non-blocking reference-program-compare matrix across one or more frozen families",
    )
    reference_program_compare_matrix_parser.add_argument(
        "--group",
        choices=_reference_program_compare_group_names(),
        default="all",
        help="Select a frozen reference-program family preset when no explicit --family is provided",
    )
    reference_program_compare_matrix_parser.add_argument(
        "--family",
        choices=_reference_program_compare_family_names(),
        action="append",
        default=[],
        help="Restrict the run to one or more explicit reference-program families; repeat to build a smaller matrix",
    )
    reference_program_compare_matrix_parser.add_argument(
        "--summary",
        default="",
        help="Override the reference-program-compare matrix output path",
    )

    reference_program_compare_refresh_parser = subparsers.add_parser(
        "reference-program-compare-refresh",
        help="Refresh the stable non-blocking reference-program-compare supplementary surface and derived observer/current-state views",
    )
    reference_program_compare_refresh_parser.add_argument(
        "--group",
        choices=_reference_program_compare_group_names(),
        default="all",
        help="Frozen family preset to refresh into the stable reference_program_compare surface",
    )
    reference_program_compare_refresh_parser.add_argument(
        "--family",
        choices=_reference_program_compare_family_names(),
        action="append",
        default=[],
        help="Restrict the refresh to one or more explicit families; repeat to build a smaller matrix",
    )
    reference_program_compare_refresh_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )

    family_asset_audit_parser = subparsers.add_parser(
        "family-asset-audit",
        help="Audit equivalence-family asset seams without creating a second authority",
    )
    family_asset_audit_parser.add_argument(
        "--family",
        choices=tuple(_family_asset_audit_families()),
        default=None,
        help="Restrict the asset seam audit to one family; default audits the full known surface",
    )
    family_asset_audit_parser.add_argument(
        "--output",
        default="",
        help="Override the family asset audit output path",
    )

    family_lane_parser = subparsers.add_parser(
        "family-lane",
        help="Run one subset equivalence lane by cloning a family spec pair and applying safe overrides",
    )
    family_lane_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        default=None,
        help="Equivalence family whose baseline/runtime specs should be cloned",
    )
    family_lane_parser.add_argument(
        "--preset",
        choices=_family_lane_preset_names(mode="lane"),
        default=None,
        help="Named research-only subset lane preset",
    )
    _add_family_lane_override_arguments(family_lane_parser)
    family_lane_parser.add_argument(
        "--output",
        default="",
        help="Override the subset lane summary output path",
    )

    family_lane_preset_parser = subparsers.add_parser(
        "family-lane-preset",
        help="Run one named research-only subset lane preset without changing stable authority",
    )
    family_lane_preset_parser.add_argument(
        "--preset",
        choices=_family_lane_preset_names(mode="lane"),
        required=True,
        help="Named research-only subset lane preset",
    )
    _add_family_lane_override_arguments(family_lane_preset_parser)
    family_lane_preset_parser.add_argument(
        "--output",
        default="",
        help="Override the preset lane summary output path",
    )

    family_lane_matrix_parser = subparsers.add_parser(
        "family-lane-matrix",
        help="Run a small non-canonical research matrix by applying one shared override bundle to multiple families",
    )
    family_lane_matrix_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        action="append",
        default=[],
        help="Add one explicit equivalence family to the non-canonical lane matrix; repeat as needed",
    )
    family_lane_matrix_parser.add_argument(
        "--preset",
        choices=_family_lane_preset_names(mode="matrix"),
        default=None,
        help="Named research-only subset matrix preset",
    )
    _add_family_lane_override_arguments(family_lane_matrix_parser)
    family_lane_matrix_parser.add_argument(
        "--output",
        default="",
        help="Override the subset lane matrix summary output path",
    )

    family_lane_matrix_preset_parser = subparsers.add_parser(
        "family-lane-matrix-preset",
        help="Run one named research-only subset matrix preset without changing stable authority",
    )
    family_lane_matrix_preset_parser.add_argument(
        "--preset",
        choices=_family_lane_preset_names(mode="matrix"),
        required=True,
        help="Named research-only subset matrix preset",
    )
    _add_family_lane_override_arguments(family_lane_matrix_preset_parser)
    family_lane_matrix_preset_parser.add_argument(
        "--output",
        default="",
        help="Override the preset lane matrix summary output path",
    )

    nightly_parser = subparsers.add_parser(
        "nightly",
        help="Run the explicit nightly experimental gate: builder matrix, toolchain matrix, toolchain audit, then emit one top-level index",
    )
    nightly_parser.add_argument(
        "--no-register",
        action="store_true",
        help="Skip manifest registration for the per-program matrix runs",
    )
    nightly_parser.add_argument(
        "--no-protocol",
        action="store_true",
        help="Skip the explicit protocol precheck before the toolchain bridge audit step",
    )
    nightly_parser.add_argument(
        "--summary",
        default="",
        help="Override the top-level nightly index output path",
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Refresh the stable multi-date nightly history index from dated nightly index snapshots",
    )
    history_parser.add_argument(
        "--summary",
        default="",
        help="Override the stable history index output path",
    )

    sidecar_parser = subparsers.add_parser(
        "sidecar",
        help="Run the isolated nightly CI sidecar gate and emit a stable gate report for automation",
    )
    sidecar_parser.add_argument(
        "--min-count",
        type=int,
        default=None,
        help="Override the required nightly family count; default derives from the authority family surface",
    )
    sidecar_parser.add_argument(
        "--no-register",
        action="store_true",
        help="Skip manifest registration for the underlying nightly matrix runs",
    )
    sidecar_parser.add_argument(
        "--no-protocol",
        action="store_true",
        help="Skip the toolchain audit protocol precheck in the underlying nightly gate",
    )
    sidecar_parser.add_argument(
        "--summary",
        default="",
        help="Override the dated nightly index output path used by the underlying nightly run",
    )
    sidecar_parser.add_argument(
        "--history",
        default="",
        help="Override the stable history index output path",
    )
    sidecar_parser.add_argument(
        "--report",
        default="",
        help="Override the stable sidecar gate report output path",
    )
    sidecar_parser.add_argument(
        "--with-equivalence",
        action="store_true",
        help="Attach the dated equivalence matrix to the sidecar report and fold it into the top-level experimental gate",
    )
    sidecar_parser.add_argument(
        "--with-full-equivalence",
        action="store_true",
        help="Attach the dated full-all equivalence snapshot as a research-only non-blocking section",
    )
    sidecar_parser.add_argument(
        "--with-optional-group",
        action="append",
        default=[],
        choices=tuple(sorted(_mainline_optional_groups())),
        help=(
            "Attach one authority-defined optional-group equivalence surface as a research-only non-blocking "
            "section; repeat as needed"
        ),
    )
    sidecar_parser.add_argument(
        "--with-queue-equivalence",
        action="store_true",
        help=(
            "Attach the dated queue_optional equivalence matrix as a research-only non-blocking section "
            "without changing the default authority-required family gate"
        ),
    )
    sidecar_parser.add_argument(
        "--with-abi-audit",
        action="store_true",
        help="Attach the dated ABI authority audit to the sidecar report without making it a blocking gate",
    )
    sidecar_parser.add_argument(
        "--with-artifact-isolation",
        action="store_true",
        help="Attach the stable artifact-isolation verifier report as a research-only non-blocking section",
    )

    artifact_isolation_parser = subparsers.add_parser(
        "artifact-isolation",
        help="Verify subset builder/toolchain/audit/nightly runs do not overwrite canonical dated artifacts",
    )
    artifact_isolation_parser.add_argument(
        "--report",
        default="",
        help="Override the stable artifact-isolation report output path",
    )

    subparsers.add_parser(
        "explain-sidecar",
        help="Print the stable/dated authority roles for the experimental sidecar surface",
    )
    subparsers.add_parser(
        "explain-mainline",
        help="Print the current machine-readable mainline gate authority surface",
    )
    explain_runtime_gate_parser = subparsers.add_parser(
        "explain-runtime-gate",
        help="Print the machine-readable runtime gate policy surface for one equivalence family",
    )
    explain_runtime_gate_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        required=True,
        help="Equivalence family to explain",
    )
    explain_program_semantics_parser = subparsers.add_parser(
        "explain-program-semantics",
        help="Print the authority-backed program semantics surface for one equivalence family",
    )
    explain_program_semantics_parser.add_argument(
        "--family",
        choices=tuple(sorted(EQUIV_FAMILY_SPECS)),
        required=True,
        help="Equivalence family to explain",
    )

    hart_ref_parser = subparsers.add_parser(
        "hart-ref",
        help="Run the isolated standard RISC-V hart reference bridge without mixing in custom msnn semantics",
    )
    hart_ref_parser.add_argument(
        "--profile",
        required=True,
        help="Profile key from riscv_snn_isa_lab/hart_ref/manifest.json",
    )
    hart_ref_parser.add_argument(
        "--summary",
        default="",
        help="Override the dated hart reference summary output path",
    )
    hart_ref_parser.add_argument(
        "--spike",
        default="",
        help="Optional explicit spike binary path; otherwise prefers local isolated prefix then PATH",
    )

    spike_local_parser = subparsers.add_parser(
        "spike-local",
        help="Probe the isolated local Spike dependency stack under riscv_snn_isa_lab without touching the default host path",
    )
    spike_local_parser.add_argument(
        "--summary",
        default="",
        help="Override the dated local Spike probe summary output path",
    )

    abi_export_parser = subparsers.add_parser(
        "abi-export",
        help="Export the frozen riscv_snn accelerator ABI include from the machine-readable authority file",
    )
    abi_export_parser.add_argument(
        "--authority",
        default="",
        help="Override the ABI authority JSON path",
    )
    abi_export_parser.add_argument(
        "--output",
        default="",
        help="Override the output include path",
    )

    abi_audit_parser = subparsers.add_parser(
        "abi-audit",
        help="Audit the checked-in ABI include and toolchain bridges against the single authority JSON",
    )
    abi_audit_parser.add_argument(
        "--authority",
        default="",
        help="Override the ABI authority JSON path",
    )
    abi_audit_parser.add_argument(
        "--summary",
        default="",
        help="Override the dated ABI audit summary path",
    )

    control_plane_export_parser = subparsers.add_parser(
        "export-control-plane-contract",
        help="Render the frozen control-plane contract from the ABI authority without creating a second authority",
    )
    control_plane_export_parser.add_argument(
        "--authority",
        default="",
        help="Override the ABI authority JSON path",
    )
    control_plane_export_parser.add_argument(
        "--output",
        default="",
        help="Override the markdown output path",
    )
    control_plane_export_parser.add_argument(
        "--json-output",
        default="",
        help="Optionally also write a normalized JSON contract payload",
    )

    family_admission_parser = subparsers.add_parser(
        "family-admission-audit",
        help="Evaluate an optional equivalence family group for promotion readiness without changing the blocking gate",
    )
    family_admission_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default="queue_optional",
        help="Optional family group to audit",
    )
    family_admission_parser.add_argument(
        "--summary",
        default="",
        help="Override the dated admission audit summary path",
    )

    optional_history_refresh_parser = subparsers.add_parser(
        "optional-history-refresh",
        help="Refresh the stable optional-group equivalence history from explicit curated samples or dated references",
    )
    optional_history_refresh_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default="queue_optional",
        help="Optional family group whose stable history should be refreshed",
    )
    optional_history_refresh_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to the optional history; repeat as needed",
    )
    optional_history_refresh_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the existing stable optional history before applying explicit samples",
    )
    optional_history_refresh_parser.add_argument(
        "--compact-since-latest-recovery",
        action="store_true",
        help="Compact the refreshed optional history to samples on or after the latest recovery boundary",
    )
    optional_history_refresh_parser.add_argument(
        "--output",
        default="",
        help="Override the stable optional history output path",
    )
    observer_history_refresh_parser = subparsers.add_parser(
        "observer-history-refresh",
        help="Refresh the stable observer full-equivalence history from explicit samples, with optional latest-recovery compaction",
    )
    observer_history_refresh_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to observer history; repeat as needed",
    )
    observer_history_refresh_parser.add_argument(
        "--compact-since-latest-recovery",
        action="store_true",
        help="Compact observer history to samples on or after the latest recovery boundary",
    )
    observer_history_refresh_parser.add_argument(
        "--output",
        default="",
        help="Override the stable observer history output path",
    )
    observer_history_compact_refresh_parser = subparsers.add_parser(
        "observer-history-compact-refresh",
        help="Refresh the stable observer full-equivalence history and compact it to the latest recovery boundary",
    )
    observer_history_compact_refresh_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to observer history before compacting; repeat as needed",
    )
    observer_history_compact_refresh_parser.add_argument(
        "--output",
        default="",
        help="Override the stable observer history output path",
    )

    promotion_dossier_parser = subparsers.add_parser(
        "optional-promotion-dossier",
        help="Export a compact optional promotion dossier from the family admission audit without introducing another authority",
    )
    promotion_dossier_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default="queue_optional",
        help="Optional family group to document",
    )
    promotion_dossier_parser.add_argument(
        "--output",
        default="",
        help="Override the promotion dossier output path",
    )

    family_promotion_dossier_parser = subparsers.add_parser(
        "family-promotion-dossier",
        help="Export the family promotion dossier alias without introducing another authority",
    )
    family_promotion_dossier_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default="queue_optional",
        help="Optional family group to document",
    )
    family_promotion_dossier_parser.add_argument(
        "--output",
        default="",
        help="Override the promotion dossier output path",
    )

    research_parser = subparsers.add_parser(
        "research-report",
        help="Export the research-metrics summary from stable sidecar/equivalence artifacts without changing gate authority",
    )
    research_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    research_parser.add_argument(
        "--output",
        default="",
        help="Override the research report output path",
    )

    observer_validate_parser = subparsers.add_parser(
        "observer-adequacy-validate",
        help=(
            "Validate the compact observer/research full-equivalence rollup against canonical "
            "full-equivalence history when real fail/recovery samples are present"
        ),
    )
    observer_validate_parser.add_argument(
        "--report",
        default="",
        help="Override the input report path; accepts a stable research report or stable sidecar report",
    )
    observer_validate_parser.add_argument(
        "--output",
        default="",
        help="Override the observer adequacy validation summary output path",
    )

    mainline_status_parser = subparsers.add_parser(
        "export-mainline-status",
        help="Render the shared current-mainline status surface from stable sidecar and derived references",
    )
    mainline_status_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    mainline_status_parser.add_argument(
        "--output",
        default="",
        help="Override the markdown output path",
    )

    stable_surface_audit_parser = subparsers.add_parser(
        "stable-surface-audit",
        help="Audit stable sidecar-derived surfaces for single-authority refresh consistency",
    )
    stable_surface_audit_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    stable_surface_audit_parser.add_argument(
        "--output",
        default="",
        help="Override the stable surface refresh audit output path",
    )

    observer_refresh_parser = subparsers.add_parser(
        "observer-refresh",
        help="Refresh stable observer/research/current-state surfaces and optionally ingest fail/recovery samples",
    )
    observer_refresh_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    observer_refresh_parser.add_argument(
        "--observer-summary",
        default="",
        help="Override the stable observer summary output path",
    )
    observer_refresh_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to observer history; repeat as needed",
    )

    mainline_refresh_parser = subparsers.add_parser(
        "mainline-refresh",
        help="Refresh observer/research/current-mainline surfaces and the optional promotion dossier in one shot",
    )
    mainline_refresh_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default=None,
        help="Optional family group to document during the mainline refresh",
    )
    mainline_refresh_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    mainline_refresh_parser.add_argument(
        "--observer-summary",
        default="",
        help="Override the stable observer summary output path",
    )
    mainline_refresh_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to observer history; repeat as needed",
    )
    mainline_refresh_parser.add_argument(
        "--dossier-output",
        default="",
        help="Override the optional promotion dossier output path",
    )
    observer_fail_recovery_parser = subparsers.add_parser(
        "observer-fail-recovery",
        help="Run one formal fail/recovery closure loop: optional history refresh + mainline surface refresh + stable surface audit",
    )
    observer_fail_recovery_parser.add_argument(
        "--group",
        choices=tuple(sorted(_mainline_optional_groups())),
        default=None,
        help="Optional family group to use; default derives from authority mainline refresh group",
    )
    observer_fail_recovery_parser.add_argument(
        "--sidecar",
        default="",
        help="Override the stable sidecar gate report path",
    )
    observer_fail_recovery_parser.add_argument(
        "--observer-summary",
        default="",
        help="Override the stable observer summary output path",
    )
    observer_fail_recovery_parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help="Add one dated equivalence sample to observer history and optional history; repeat as needed",
    )
    observer_fail_recovery_parser.add_argument(
        "--dossier-output",
        default="",
        help="Override the optional promotion dossier output path",
    )
    observer_fail_recovery_parser.add_argument(
        "--optional-history-output",
        default="",
        help="Override the optional history output path",
    )
    observer_fail_recovery_parser.add_argument(
        "--audit-output",
        default="",
        help="Override the stable surface audit output path",
    )
    observer_fail_recovery_parser.add_argument(
        "--output",
        default="",
        help="Override the observer fail/recovery loop summary output path",
    )

    register_parser = subparsers.add_parser("register", help="Create a run manifest draft for a completed smoke run")
    register_parser.add_argument("--program", required=True, help="Sample firmware program")
    register_parser.add_argument("--run-dir", required=True, help="Completed run directory")
    register_parser.add_argument("--manifest", default="", help="Override output manifest path")

    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            _print_completed_process(list_programs(as_json=bool(args.json)))
            return 0
        if args.command == "generate":
            elf_path, spec_path = generate_program(
                args.program,
                elf_path=Path(args.elf) if args.elf else None,
                spec_path=Path(args.spec) if args.spec else None,
            )
            print(elf_path)
            print(spec_path)
            return 0
        if args.command == "validate":
            proc = validate_program(
                program=args.program,
                spec_path=Path(args.spec) if args.spec else None,
            )
            _print_completed_process(proc)
            return 0
        if args.command == "smoke":
            run_dir = smoke_program(
                args.program,
                spec_path=Path(args.spec) if args.spec else None,
            )
            print(run_dir)
            return 0
        if args.command == "runtime-bridge-preflight":
            summary = run_runtime_bridge_preflight(
                program=args.program,
                spec_path=Path(args.spec) if args.spec else None,
            )
            print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
            return 0 if summary["status"] in {"ok", "skipped"} and not summary.get("full_rebuild_required") else 2
        if args.command == "protocol":
            proc = run_protocol_suite(args.suite)
            _print_completed_process(proc)
            return 0
        if args.command == "regress":
            run_dir, manifest_path = run_regression(
                args.program,
                suite=args.suite,
                register=bool(args.register),
                manifest_path=Path(args.manifest) if args.manifest else None,
            )
            print(run_dir)
            if manifest_path is not None:
                print(manifest_path)
            return 0
        if args.command == "matrix":
            summary = run_matrix(
                args.group,
                register=bool(args.register),
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0
        if args.command == "audit":
            summary = audit_programs(
                args.group,
                protocol=bool(args.protocol),
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "equiv":
            summary = run_equivalence(
                args.family,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["status"] == "PASS" else 2
        if args.command == "equiv-matrix":
            summary = run_equiv_matrix(
                families=list(args.family) if args.family else None,
                group=args.group,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "reference-compare":
            summary = run_reference_compare_family(
                family=args.family,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["gate_ok"] else 2
        if args.command == "reference-compare-matrix":
            summary = run_reference_compare_matrix(
                families=list(args.family) if args.family else None,
                group=args.group,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "reference-compare-refresh":
            summary = refresh_reference_compare_surface(
                families=list(args.family) if args.family else None,
                group=args.group,
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
            )
            print(Path(summary["report_path"]))
            return 0 if summary["gate_ok"] else 2
        if args.command == "reference-program-compare":
            summary = run_reference_program_compare_family(
                family=args.family,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["gate_ok"] else 2
        if args.command == "reference-program-compare-matrix":
            summary = run_reference_program_compare_matrix(
                families=list(args.family) if args.family else None,
                group=args.group,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "reference-program-compare-refresh":
            summary = refresh_reference_program_compare_surface(
                families=list(args.family) if args.family else None,
                group=args.group,
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
            )
            print(Path(summary["report_path"]))
            return 0 if summary["gate_ok"] else 2
        if args.command == "family-asset-audit":
            summary = audit_family_assets(
                family=args.family,
                output_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "family-lane":
            summary = run_family_lane(
                family=args.family,
                preset=args.preset,
                sim_time=args.sim_time,
                mesh_size=args.mesh_size,
                hart_isa=args.hart_isa,
                local_mem_bytes=args.local_mem_bytes,
                cmd_queue_entries=args.cmd_queue_entries,
                cmp_queue_entries=args.cmp_queue_entries,
                rx_debug_queue_entries=args.rx_debug_queue_entries,
                boot_addr=args.boot_addr,
                summary_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary.get("status", "PASS") == "PASS" else 2
        if args.command == "family-lane-preset":
            summary = run_family_lane_preset(
                preset=args.preset,
                sim_time=args.sim_time,
                mesh_size=args.mesh_size,
                hart_isa=args.hart_isa,
                local_mem_bytes=args.local_mem_bytes,
                cmd_queue_entries=args.cmd_queue_entries,
                cmp_queue_entries=args.cmp_queue_entries,
                rx_debug_queue_entries=args.rx_debug_queue_entries,
                boot_addr=args.boot_addr,
                summary_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary.get("status", "PASS") == "PASS" else 2
        if args.command == "family-lane-matrix":
            summary = run_family_lane_matrix(
                families=list(args.family) if args.family else None,
                preset=args.preset,
                sim_time=args.sim_time,
                mesh_size=args.mesh_size,
                hart_isa=args.hart_isa,
                local_mem_bytes=args.local_mem_bytes,
                cmd_queue_entries=args.cmd_queue_entries,
                cmp_queue_entries=args.cmp_queue_entries,
                rx_debug_queue_entries=args.rx_debug_queue_entries,
                boot_addr=args.boot_addr,
                summary_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "family-lane-matrix-preset":
            summary = run_family_lane_matrix_preset(
                preset=args.preset,
                sim_time=args.sim_time,
                mesh_size=args.mesh_size,
                hart_isa=args.hart_isa,
                local_mem_bytes=args.local_mem_bytes,
                cmd_queue_entries=args.cmd_queue_entries,
                cmp_queue_entries=args.cmp_queue_entries,
                rx_debug_queue_entries=args.rx_debug_queue_entries,
                boot_addr=args.boot_addr,
                summary_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "nightly":
            summary = run_nightly(
                register=not bool(args.no_register),
                protocol=not bool(args.no_protocol),
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "history":
            summary = refresh_history_index(
                output_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok_latest"] else 2
        if args.command == "sidecar":
            report = run_ci_sidecar(
                min_count=int(args.min_count) if args.min_count is not None else None,
                register=not bool(args.no_register),
                protocol=not bool(args.no_protocol),
                with_equivalence=bool(args.with_equivalence),
                with_full_equivalence=bool(args.with_full_equivalence),
                with_optional_groups=list(args.with_optional_group) if args.with_optional_group else None,
                with_queue_equivalence=bool(args.with_queue_equivalence),
                with_abi_audit=bool(args.with_abi_audit),
                with_artifact_isolation=bool(args.with_artifact_isolation),
                summary_path=Path(args.summary) if args.summary else None,
                history_path=Path(args.history) if args.history else None,
                report_path=Path(args.report) if args.report else None,
            )
            print(report["report_path"])
            return 0 if report["gate_ok"] else 2
        if args.command == "artifact-isolation":
            report = run_artifact_isolation_check(
                report_path=Path(args.report) if args.report else None,
            )
            print(report["summary_path"])
            return 0 if report["all_ok"] else 2
        if args.command == "explain-sidecar":
            print(explain_sidecar_surface())
            return 0
        if args.command == "explain-mainline":
            print(explain_mainline_surface())
            return 0
        if args.command == "explain-runtime-gate":
            print(explain_runtime_gate_surface(args.family))
            return 0
        if args.command == "explain-program-semantics":
            print(explain_program_semantics_surface(args.family))
            return 0
        if args.command == "hart-ref":
            summary = run_hart_ref(
                profile=args.profile,
                summary_path=Path(args.summary) if args.summary else None,
                spike_path=Path(args.spike) if args.spike else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "spike-local":
            summary = probe_spike_local(
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "abi-export":
            output_path = export_abi_include(
                authority_path=Path(args.authority) if args.authority else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "abi-audit":
            summary = audit_abi_surface(
                authority_path=Path(args.authority) if args.authority else None,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0 if summary["all_ok"] else 2
        if args.command == "export-control-plane-contract":
            outputs = export_control_plane_contract(
                authority_path=Path(args.authority) if args.authority else None,
                output_path=Path(args.output) if args.output else None,
                json_output_path=Path(args.json_output) if args.json_output else None,
            )
            print(Path(outputs["markdown_path"]))
            return 0
        if args.command == "family-admission-audit":
            summary = run_family_admission_audit(
                group=args.group,
                summary_path=Path(args.summary) if args.summary else None,
            )
            print(summary["summary_path"])
            return 0
        if args.command == "optional-history-refresh":
            summary = refresh_optional_equivalence_history(
                group=args.group,
                sample_paths=[Path(path) for path in args.sample] if args.sample else None,
                compact_since_latest_recovery=bool(args.compact_since_latest_recovery),
                reset_existing=bool(args.reset),
                output_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0
        if args.command in {"observer-history-refresh", "observer-history-compact-refresh"}:
            compact_since_latest_recovery = (
                bool(getattr(args, "compact_since_latest_recovery", False))
                or args.command == "observer-history-compact-refresh"
            )
            history = refresh_observer_history_surface(
                sample_paths=[Path(path) for path in getattr(args, "sample", [])] or None,
                compact_since_latest_recovery=compact_since_latest_recovery,
                output_path=Path(args.output) if args.output else None,
            )
            print(Path(history["summary_path"]))
            return 0
        if args.command == "optional-promotion-dossier":
            output_path = export_optional_promotion_dossier(
                group=args.group,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "family-promotion-dossier":
            output_path = export_family_promotion_dossier(
                group=args.group,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "research-report":
            output_path = export_research_report(
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "observer-adequacy-validate":
            output_path = validate_observer_adequacy(
                report_path=Path(args.report) if args.report else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "export-mainline-status":
            output_path = export_mainline_status(
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(output_path)
            return 0
        if args.command == "stable-surface-audit":
            summary = audit_stable_surface_refresh(
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "observer-refresh":
            outputs = refresh_observer_surfaces(
                sample_paths=[Path(path) for path in args.sample],
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                observer_summary_path=Path(args.observer_summary) if args.observer_summary else None,
            )
            print(outputs["observer_summary_path"])
            return 0
        if args.command == "mainline-refresh":
            refresh_group = args.group or _mainline_refresh_default_group()
            if refresh_group is None:
                raise ValueError("mainline-refresh requires at least one optional group in authority")
            outputs = refresh_mainline_surfaces(
                sample_paths=[Path(path) for path in args.sample],
                group=refresh_group,
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                observer_summary_path=Path(args.observer_summary) if args.observer_summary else None,
                dossier_output_path=Path(args.dossier_output) if args.dossier_output else None,
            )
            print(outputs["current_mainline_status_path"])
            return 0
        if args.command == "observer-fail-recovery":
            summary = run_observer_fail_recovery_loop(
                group=args.group,
                sample_paths=[Path(path) for path in args.sample] if args.sample else None,
                sidecar_path=Path(args.sidecar) if args.sidecar else None,
                observer_summary_path=Path(args.observer_summary) if args.observer_summary else None,
                dossier_output_path=Path(args.dossier_output) if args.dossier_output else None,
                optional_history_output_path=Path(args.optional_history_output) if args.optional_history_output else None,
                stable_surface_audit_output_path=Path(args.audit_output) if args.audit_output else None,
                output_path=Path(args.output) if args.output else None,
            )
            print(Path(summary["summary_path"]))
            return 0 if summary["all_ok"] else 2
        if args.command == "register":
            sample_manifest = _load_program_manifest()
            manifest_path = register_run(
                args.program,
                Path(args.run_dir),
                manifest_path=Path(args.manifest) if args.manifest else None,
                sample_manifest=sample_manifest,
            )
            print(manifest_path)
            return 0
    except (FileNotFoundError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(str(exc))
        sys.stderr.write("\n")
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
