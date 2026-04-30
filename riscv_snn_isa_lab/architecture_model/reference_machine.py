from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .fabric_model import FabricModel
from .fused_step_model import FusedStepModel
from .memory_model import MemoryModel
from .model_types import (
    ReferenceProgramRequest,
    ReferenceProgramResult,
    ReferenceProgramTraceEntry,
    ReferenceStepRequest,
    ReferenceStepResult,
)
from .program_profile_model import (
    _fault_snapshot_label,
    _normalize_snapshot_summary,
    _snapshot_signature,
)


@dataclass(frozen=True)
class ReferenceMachine:
    authority_domain: str
    fused_step: FusedStepModel
    memory: MemoryModel
    fabric: FabricModel

    @classmethod
    def from_authority(cls, authority: dict[str, Any]) -> "ReferenceMachine":
        required_sections = (
            "authority_domain",
            "fused_step_state_machine",
            "memory_taxonomy",
            "fabric_taxonomy",
        )
        missing_sections = [section for section in required_sections if section not in authority]
        if missing_sections:
            raise ValueError(
                "missing required architecture authority sections: "
                + ", ".join(missing_sections)
            )
        return cls(
            authority_domain=str(authority["authority_domain"]),
            fused_step=FusedStepModel.from_authority(authority["fused_step_state_machine"]),
            memory=MemoryModel.from_authority(authority["memory_taxonomy"]),
            fabric=FabricModel.from_authority(authority["fabric_taxonomy"]),
        )

    @classmethod
    def from_lab_root(cls, *, lab_root: Any | None = None) -> "ReferenceMachine":
        from riscv_snn_isa_lab.tools import riscv_snn_lab

        if lab_root is None:
            authority = riscv_snn_lab.load_architecture_model_authority()
        else:
            authority = riscv_snn_lab.load_architecture_model_authority(lab_root=lab_root)
        return cls.from_authority(authority)

    def execute_fused_step(
        self,
        *,
        condition_values: dict[str, bool],
        metadata: dict[str, Any] | None = None,
    ) -> ReferenceStepResult:
        resolved_metadata = {} if metadata is None else dict(metadata)
        request = ReferenceStepRequest(
            condition_values=dict(condition_values),
            metadata=resolved_metadata,
        )
        result = self.fused_step.execute(request)
        memory_events = self.memory.account_domains(list(resolved_metadata.get("memory_domains", [])))
        fabric_events = self.fabric.account_stages(list(resolved_metadata.get("fabric_stages", [])))
        divergence_observations = self.fabric.account_divergence_points(
            list(resolved_metadata.get("divergence_points", []))
        )
        microarchitectural_progress = dict(result.microarchitectural_progress)
        microarchitectural_progress["memory_event_count"] = len(memory_events)
        microarchitectural_progress["fabric_event_count"] = len(fabric_events)
        microarchitectural_progress["divergence_count"] = len(divergence_observations)
        return replace(
            result,
            microarchitectural_progress=microarchitectural_progress,
            memory_events=memory_events,
            fabric_events=fabric_events,
            divergence_observations=divergence_observations,
        )

    def execute_stat_snapshot(
        self,
        *,
        condition_values: dict[str, bool],
        metadata: dict[str, Any] | None = None,
    ) -> ReferenceStepResult:
        resolved_metadata = {} if metadata is None else dict(metadata)
        terminal_state = str(resolved_metadata.get("terminal_state") or "").strip()
        if not terminal_state:
            terminal_state = "Faulted" if condition_values.get("fault_classified") else "Completed"
        if terminal_state not in {"Completed", "Faulted"}:
            raise ValueError(f"unsupported stat_snapshot terminal state: {terminal_state}")

        snapshot_summary = _normalize_snapshot_summary(resolved_metadata.get("snapshot_summary"))
        visited_states = (
            ["StatSnapshotAccepted", "StatSnapshotFaulted"]
            if terminal_state == "Faulted"
            else ["StatSnapshotAccepted", "StatSnapshotCompleted"]
        )
        base_result = ReferenceStepResult(
            terminal_state=terminal_state,
            visited_states=visited_states,
            completion_retired=terminal_state == "Completed",
            faulted=terminal_state == "Faulted",
            architectural_state={
                "visibility_domain": "program_control_command",
                "fault_visible": terminal_state == "Faulted",
                "completion_visible": terminal_state == "Completed",
                "snapshot_visible": terminal_state == "Completed",
                "command_kind": "stat_snapshot",
                "snapshot_summary": snapshot_summary,
            },
            microarchitectural_progress={
                "completion_ready": terminal_state == "Completed",
                "fault_ready": terminal_state == "Faulted",
                "waiting_on": [],
                "control_event_count": len(list(resolved_metadata.get("control_events", []) or [])),
            },
            simulator_bookkeeping={
                "metadata": resolved_metadata,
                "state_count": len(visited_states),
            },
        )
        memory_events = self.memory.account_domains(list(resolved_metadata.get("memory_domains", [])))
        fabric_events = self.fabric.account_stages(list(resolved_metadata.get("fabric_stages", [])))
        divergence_observations = self.fabric.account_divergence_points(
            list(resolved_metadata.get("divergence_points", []))
        )
        microarchitectural_progress = dict(base_result.microarchitectural_progress)
        microarchitectural_progress["memory_event_count"] = len(memory_events)
        microarchitectural_progress["fabric_event_count"] = len(fabric_events)
        microarchitectural_progress["divergence_count"] = len(divergence_observations)
        return replace(
            base_result,
            microarchitectural_progress=microarchitectural_progress,
            memory_events=memory_events,
            fabric_events=fabric_events,
            divergence_observations=divergence_observations,
        )

    def execute_program(self, request: ReferenceProgramRequest) -> ReferenceProgramResult:
        entries: list[ReferenceProgramTraceEntry] = []
        terminal_states: list[str] = []
        command_kind_sequence: list[str] = []
        completion_step_indices: list[int] = []
        fault_step_indices: list[int] = []
        barrier_wait_step_indices: list[int] = []
        clear_fault_before_step_indices: list[int] = []
        overwrite_fault_step_indices: list[int] = []
        snapshot_step_indices: list[int] = []
        snapshot_signature_sequence: list[str] = []
        snapshot_summary_sequence: list[dict[str, Any]] = []
        fault_snapshot_sequence: list[str] = []
        memory_domain_sequences: list[list[str]] = []
        fabric_stage_sequences: list[list[str]] = []
        divergence_point_sequences: list[list[str]] = []

        for step_index, step in enumerate(request.steps):
            resolved_metadata = dict(step.metadata)
            command_kind = str(step.command_kind or resolved_metadata.get("command_kind") or "fused_step")
            command_kind_sequence.append(command_kind)
            if command_kind == "fused_step":
                result = self.execute_fused_step(
                    condition_values=dict(step.condition_values),
                    metadata=resolved_metadata,
                )
            elif command_kind == "stat_snapshot":
                result = self.execute_stat_snapshot(
                    condition_values=dict(step.condition_values),
                    metadata=resolved_metadata,
                )
            else:
                raise ValueError(f"unsupported program command kind: {command_kind}")

            snapshot_summary = _normalize_snapshot_summary(resolved_metadata.get("snapshot_summary"))
            snapshot_signature = ""
            if snapshot_summary:
                snapshot_signature = _snapshot_signature(snapshot_summary)
                snapshot_step_indices.append(step_index)
                snapshot_signature_sequence.append(snapshot_signature)
                snapshot_summary_sequence.append(snapshot_summary)
            entries.append(
                ReferenceProgramTraceEntry(
                    step_index=step_index,
                    step_name=step.step_name,
                    command_kind=command_kind,
                    result=result,
                    metadata=resolved_metadata,
                    clear_fault_before_step=bool(step.clear_fault_before_step),
                    overwrite_visible_fault_snapshot=bool(step.overwrite_visible_fault_snapshot),
                )
            )
            terminal_states.append(result.terminal_state)
            if result.completion_retired:
                completion_step_indices.append(step_index)
            if result.faulted:
                fault_step_indices.append(step_index)
                fault_snapshot_sequence.append(
                    _fault_snapshot_label(
                        step_index=step_index,
                        command_kind=command_kind,
                        snapshot_summary=snapshot_summary,
                    )
                )
            if result.terminal_state == "BarrierWaiting":
                barrier_wait_step_indices.append(step_index)
            if step.clear_fault_before_step:
                clear_fault_before_step_indices.append(step_index)
            if step.overwrite_visible_fault_snapshot:
                overwrite_fault_step_indices.append(step_index)

            memory_domain_sequences.append([event.domain for event in result.memory_events])
            fabric_stage_sequences.append([event.stage for event in result.fabric_events])
            divergence_point_sequences.append(
                [event.kind for event in result.divergence_observations]
            )

        terminal_state = terminal_states[-1] if terminal_states else "Idle"
        return ReferenceProgramResult(
            family=request.family,
            step_count=len(entries),
            terminal_state=terminal_state,
            terminal_states=terminal_states,
            entries=entries,
            command_kind_sequence=command_kind_sequence,
            completion_step_indices=completion_step_indices,
            fault_step_indices=fault_step_indices,
            barrier_wait_step_indices=barrier_wait_step_indices,
            clear_fault_before_step_indices=clear_fault_before_step_indices,
            overwrite_fault_step_indices=overwrite_fault_step_indices,
            snapshot_step_indices=snapshot_step_indices,
            snapshot_signature_sequence=snapshot_signature_sequence,
            snapshot_summary_sequence=snapshot_summary_sequence,
            fault_snapshot_sequence=fault_snapshot_sequence,
            memory_domain_sequences=memory_domain_sequences,
            fabric_stage_sequences=fabric_stage_sequences,
            divergence_point_sequences=divergence_point_sequences,
            metadata=dict(request.metadata),
        )
