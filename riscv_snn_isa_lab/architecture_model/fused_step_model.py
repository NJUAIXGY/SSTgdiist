from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from riscv_snn_isa_lab.architecture_model.model_types import (
    CompletionBoundary,
    FusedStepState,
    ReferenceStepRequest,
    ReferenceStepResult,
    StateMachine,
)


@dataclass
class FusedStepModel:
    state_machine: StateMachine

    @classmethod
    def from_authority(cls, authority: Dict[str, Any]) -> "FusedStepModel":
        section = authority.get("fused_step_state_machine", authority)
        if section is None:
            raise ValueError("authority missing fused_step_state_machine")

        def build_state(data: Dict[str, Any]) -> FusedStepState:
            return FusedStepState(
                name=data["name"],
                entry_condition=data["entry_condition"],
                exit_condition=data["exit_condition"],
                architecturally_visible=bool(data["architecturally_visible"]),
                microarchitectural_only=bool(data["microarchitectural_only"]),
                simulator_bookkeeping_only=bool(data["simulator_bookkeeping_only"]),
                counter_groups=list(data.get("counter_groups", [])),
            )

        def build_boundary(data: Dict[str, Any]) -> CompletionBoundary:
            return CompletionBoundary(
                boundary_name=data["boundary_name"],
                required_conditions=list(data.get("required_conditions", [])),
            )

        states = [build_state(state) for state in section["states"]]
        completion = build_boundary(section["completion_boundary"])
        fault = build_boundary(section["fault_boundary"])
        visibility = dict(section["visibility_domains"])

        state_machine = StateMachine(
            semantic_statement=section.get("semantic_statement", ""),
            completion_boundary=completion,
            fault_boundary=fault,
            visibility_domains=visibility,
            states=states,
        )

        return cls(state_machine=state_machine)

    def state_names(self) -> list[str]:
        return [state.name for state in self.state_machine.states]

    def execute(self, request: ReferenceStepRequest) -> ReferenceStepResult:
        completion_ready = self._boundary_ready(
            self.state_machine.completion_boundary.required_conditions,
            request.condition_values,
        )
        fault_ready = self._boundary_ready(
            self.state_machine.fault_boundary.required_conditions,
            request.condition_values,
        )

        active_states = [name for name in self.state_names() if name != "Idle"]
        waiting_prefix = [name for name in active_states if name != "Completed" and name != "Faulted"]

        if fault_ready:
            visited_states = waiting_prefix + ["Faulted"]
            return ReferenceStepResult(
                terminal_state="Faulted",
                visited_states=visited_states,
                completion_retired=False,
                faulted=True,
                architectural_state={
                    "visibility_domain": "fault_boundary",
                    "fault_visible": True,
                    "completion_visible": False,
                },
                microarchitectural_progress={
                    "completion_ready": completion_ready,
                    "fault_ready": fault_ready,
                    "waiting_on": [],
                },
                simulator_bookkeeping={
                    "metadata": dict(request.metadata),
                    "state_count": len(visited_states),
                },
            )

        if completion_ready:
            visited_states = waiting_prefix + ["Completed"]
            return ReferenceStepResult(
                terminal_state="Completed",
                visited_states=visited_states,
                completion_retired=True,
                faulted=False,
                architectural_state={
                    "visibility_domain": "architectural_state",
                    "fault_visible": False,
                    "completion_visible": True,
                },
                microarchitectural_progress={
                    "completion_ready": completion_ready,
                    "fault_ready": fault_ready,
                    "waiting_on": [],
                },
                simulator_bookkeeping={
                    "metadata": dict(request.metadata),
                    "state_count": len(visited_states),
                },
            )

        waiting_on = [
            condition
            for condition in self.state_machine.completion_boundary.required_conditions
            if not request.condition_values.get(condition, False)
        ]
        return ReferenceStepResult(
            terminal_state="BarrierWaiting",
            visited_states=waiting_prefix,
            completion_retired=False,
            faulted=False,
            architectural_state={
                "visibility_domain": "architectural_state",
                "fault_visible": False,
                "completion_visible": False,
            },
            microarchitectural_progress={
                "completion_ready": completion_ready,
                "fault_ready": fault_ready,
                "waiting_on": waiting_on,
            },
            simulator_bookkeeping={
                "metadata": dict(request.metadata),
                "state_count": len(waiting_prefix),
            },
        )

    @staticmethod
    def _boundary_ready(required_conditions: list[str], condition_values: Dict[str, bool]) -> bool:
        return all(condition_values.get(condition, False) for condition in required_conditions)
