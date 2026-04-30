from __future__ import annotations

from typing import Any

from .model_types import ReferenceProgramResult, ReferenceStepResult


def compare_reference_to_runtime(
    reference_result: ReferenceStepResult,
    runtime_summary: dict[str, Any],
    *,
    allowed_divergence_points: tuple[str, ...],
) -> dict[str, Any]:
    reference_memory_domains = [event.domain for event in reference_result.memory_events]
    reference_fabric_stages = [event.stage for event in reference_result.fabric_events]
    reference_divergence_points = [event.kind for event in reference_result.divergence_observations]

    runtime_memory_domains = list(runtime_summary.get("memory_domains", []))
    runtime_fabric_stages = list(runtime_summary.get("fabric_stages", []))
    runtime_divergence_points = list(runtime_summary.get("divergence_points", []))

    terminal_state_match = reference_result.terminal_state == runtime_summary.get("terminal_state")
    memory_domain_alignment = reference_memory_domains == runtime_memory_domains
    fabric_stage_alignment = reference_fabric_stages == runtime_fabric_stages

    combined_divergence = sorted(set(reference_divergence_points) | set(runtime_divergence_points))
    invalid_divergence_points = [
        point for point in combined_divergence if point not in set(allowed_divergence_points)
    ]

    if terminal_state_match and memory_domain_alignment and fabric_stage_alignment and not combined_divergence:
        status = "aligned"
    elif terminal_state_match and not invalid_divergence_points and combined_divergence:
        status = "allowed_divergence"
    else:
        status = "mismatch"

    gate_ok = status in {"aligned", "allowed_divergence"}
    gate_reasons: list[str] = []
    if not terminal_state_match:
        gate_reasons.append("terminal_state_mismatch")
    if not memory_domain_alignment:
        gate_reasons.append("memory_domain_mismatch")
    if not fabric_stage_alignment:
        gate_reasons.append("fabric_stage_mismatch")
    if invalid_divergence_points:
        gate_reasons.append("invalid_divergence_point")

    return {
        "status": status,
        "gate_ok": gate_ok,
        "gate_reasons": gate_reasons,
        "terminal_state_match": terminal_state_match,
        "memory_domain_alignment": memory_domain_alignment,
        "fabric_stage_alignment": fabric_stage_alignment,
        "reference_terminal_state": reference_result.terminal_state,
        "runtime_terminal_state": runtime_summary.get("terminal_state"),
        "reference_memory_domains": reference_memory_domains,
        "runtime_memory_domains": runtime_memory_domains,
        "reference_fabric_stages": reference_fabric_stages,
        "runtime_fabric_stages": runtime_fabric_stages,
        "allowed_divergence_points": combined_divergence if not invalid_divergence_points else [],
        "invalid_divergence_points": invalid_divergence_points,
    }


def compare_reference_program_to_runtime(
    reference_result: ReferenceProgramResult,
    runtime_summary: dict[str, Any],
    *,
    allowed_divergence_points: tuple[str, ...],
) -> dict[str, Any]:
    runtime_steps = list(runtime_summary.get("steps", []) or [])
    reference_entries = list(reference_result.entries)
    step_count_match = len(reference_entries) == len(runtime_steps)

    step_comparisons: list[dict[str, Any]] = []
    allowed_divergence: set[str] = set()
    invalid_divergence: set[str] = set()
    gate_reasons: list[str] = []

    for step_index, (reference_entry, runtime_step) in enumerate(zip(reference_entries, runtime_steps)):
        comparison = compare_reference_to_runtime(
            reference_entry.result,
            {
                "terminal_state": runtime_step.get("terminal_state"),
                "memory_domains": list(runtime_step.get("memory_domains", []) or []),
                "fabric_stages": list(runtime_step.get("fabric_stages", []) or []),
                "divergence_points": list(runtime_step.get("divergence_points", []) or []),
            },
            allowed_divergence_points=allowed_divergence_points,
        )
        step_comparisons.append(
            {
                "step_index": step_index,
                "step_name": reference_entry.step_name,
                **comparison,
            }
        )
        allowed_divergence.update(comparison.get("allowed_divergence_points", []))
        invalid_divergence.update(comparison.get("invalid_divergence_points", []))
        if not comparison.get("gate_ok"):
            gate_reasons.extend(
                f"step_{step_index}_{reason}"
                for reason in list(comparison.get("gate_reasons", []) or [])
            )

    reference_terminal_states = list(reference_result.terminal_states)
    runtime_terminal_states = [str(step.get("terminal_state") or "") for step in runtime_steps]

    runtime_completion_step_indices = list(
        runtime_summary.get("completion_step_indices")
        or [
            index
            for index, step in enumerate(runtime_steps)
            if str(step.get("terminal_state") or "") == "Completed"
        ]
    )
    runtime_fault_step_indices = list(
        runtime_summary.get("fault_step_indices")
        or [
            index
            for index, step in enumerate(runtime_steps)
            if str(step.get("terminal_state") or "") == "Faulted"
        ]
    )
    runtime_barrier_wait_step_indices = list(
        runtime_summary.get("barrier_wait_step_indices")
        or [
            index
            for index, step in enumerate(runtime_steps)
            if str(step.get("terminal_state") or "") == "BarrierWaiting"
        ]
    )
    runtime_clear_fault_before_step_indices = list(
        runtime_summary.get("clear_fault_before_step_indices")
        or [
            index
            for index, step in enumerate(runtime_steps)
            if bool(step.get("clear_fault_before_step"))
        ]
    )
    runtime_overwrite_fault_step_indices = list(
        runtime_summary.get("overwrite_fault_step_indices")
        or [
            index
            for index, step in enumerate(runtime_steps)
            if bool(step.get("overwrite_visible_fault_snapshot"))
        ]
    )
    runtime_fault_snapshot_sequence = list(
        runtime_summary.get("fault_snapshot_sequence")
        or [f"fault_step_{index}" for index in runtime_fault_step_indices]
    )

    terminal_state_sequence_match = reference_terminal_states == runtime_terminal_states
    completion_step_indices_match = (
        list(reference_result.completion_step_indices) == runtime_completion_step_indices
    )
    fault_step_indices_match = list(reference_result.fault_step_indices) == runtime_fault_step_indices
    barrier_wait_step_indices_match = (
        list(reference_result.barrier_wait_step_indices) == runtime_barrier_wait_step_indices
    )
    clear_fault_before_step_indices_match = (
        list(reference_result.clear_fault_before_step_indices)
        == runtime_clear_fault_before_step_indices
    )
    overwrite_fault_step_indices_match = (
        list(reference_result.overwrite_fault_step_indices)
        == runtime_overwrite_fault_step_indices
    )
    fault_snapshot_sequence_match = (
        list(reference_result.fault_snapshot_sequence) == runtime_fault_snapshot_sequence
    )

    if not step_count_match:
        gate_reasons.append("step_count_mismatch")
    if not terminal_state_sequence_match:
        gate_reasons.append("terminal_state_sequence_mismatch")
    if not completion_step_indices_match:
        gate_reasons.append("completion_sequence_mismatch")
    if not fault_step_indices_match:
        gate_reasons.append("fault_sequence_mismatch")
    if not barrier_wait_step_indices_match:
        gate_reasons.append("barrier_wait_sequence_mismatch")
    if not clear_fault_before_step_indices_match:
        gate_reasons.append("clear_sequence_mismatch")
    if not overwrite_fault_step_indices_match:
        gate_reasons.append("overwrite_sequence_mismatch")
    if not fault_snapshot_sequence_match:
        gate_reasons.append("fault_snapshot_sequence_mismatch")
    if invalid_divergence:
        gate_reasons.append("invalid_divergence_point")

    sequence_match = (
        step_count_match
        and terminal_state_sequence_match
        and completion_step_indices_match
        and fault_step_indices_match
        and barrier_wait_step_indices_match
        and clear_fault_before_step_indices_match
        and overwrite_fault_step_indices_match
        and fault_snapshot_sequence_match
    )
    steps_gate_ok = all(bool(row.get("gate_ok")) for row in step_comparisons)
    gate_ok = sequence_match and steps_gate_ok and not invalid_divergence

    if gate_ok and allowed_divergence:
        status = "allowed_divergence"
    elif gate_ok:
        status = "aligned"
    else:
        status = "mismatch"

    return {
        "status": status,
        "gate_ok": gate_ok,
        "gate_reasons": gate_reasons,
        "step_count_match": step_count_match,
        "terminal_state_sequence_match": terminal_state_sequence_match,
        "completion_step_indices_match": completion_step_indices_match,
        "fault_step_indices_match": fault_step_indices_match,
        "barrier_wait_step_indices_match": barrier_wait_step_indices_match,
        "clear_fault_before_step_indices_match": clear_fault_before_step_indices_match,
        "overwrite_fault_step_indices_match": overwrite_fault_step_indices_match,
        "fault_snapshot_sequence_match": fault_snapshot_sequence_match,
        "reference_terminal_states": reference_terminal_states,
        "runtime_terminal_states": runtime_terminal_states,
        "reference_completion_step_indices": list(reference_result.completion_step_indices),
        "runtime_completion_step_indices": runtime_completion_step_indices,
        "reference_fault_step_indices": list(reference_result.fault_step_indices),
        "runtime_fault_step_indices": runtime_fault_step_indices,
        "reference_barrier_wait_step_indices": list(reference_result.barrier_wait_step_indices),
        "runtime_barrier_wait_step_indices": runtime_barrier_wait_step_indices,
        "reference_clear_fault_before_step_indices": list(
            reference_result.clear_fault_before_step_indices
        ),
        "runtime_clear_fault_before_step_indices": runtime_clear_fault_before_step_indices,
        "reference_overwrite_fault_step_indices": list(reference_result.overwrite_fault_step_indices),
        "runtime_overwrite_fault_step_indices": runtime_overwrite_fault_step_indices,
        "reference_fault_snapshot_sequence": list(reference_result.fault_snapshot_sequence),
        "runtime_fault_snapshot_sequence": runtime_fault_snapshot_sequence,
        "step_comparisons": step_comparisons,
        "allowed_divergence_points": sorted(allowed_divergence) if not invalid_divergence else [],
        "invalid_divergence_points": sorted(invalid_divergence),
    }
