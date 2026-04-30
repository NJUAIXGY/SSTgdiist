from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_types import ReferenceProgramRequest, ReferenceProgramStep

_KNOWN_COMMAND_KINDS = {"fused_step", "stat_snapshot"}


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _condition_values_for_terminal_state(terminal_state: str) -> dict[str, bool]:
    if terminal_state == "Faulted":
        return {
            "fault_classified": True,
            "fault_csr_committed": True,
            "completion_suppressed_or_replaced_by_fault": True,
        }
    if terminal_state == "Completed":
        return {
            "architectural_state_committed": True,
            "local_outbound_handover_complete": True,
            "barrier_release_visible": True,
            "no_higher_priority_fault_pending": True,
        }
    if terminal_state == "BarrierWaiting":
        return {
            "architectural_state_committed": True,
            "local_outbound_handover_complete": True,
            "barrier_release_visible": False,
            "no_higher_priority_fault_pending": True,
        }
    raise ValueError(f"unsupported reference program terminal state: {terminal_state}")


def _runtime_gate_divergence_points(
    family_policy: dict[str, Any],
    *,
    allowed_points: tuple[str, ...],
) -> list[str]:
    if not allowed_points:
        return []
    if str(family_policy.get("timing_mode") or "").strip():
        return [point for point in ["backpressure"] if point in allowed_points]
    if str(family_policy.get("fault_lifecycle_mode") or "").strip() in {
        "clear_then_refault",
        "overwrite_chain",
    }:
        return [point for point in ["queue_occupancy"] if point in allowed_points]
    return []


def _resolved_command_kind(step: ReferenceProgramStep) -> str:
    metadata_command_kind = str(step.metadata.get("command_kind") or "").strip()
    resolved = str(step.command_kind or metadata_command_kind or "fused_step").strip()
    if resolved not in _KNOWN_COMMAND_KINDS:
        raise ValueError(f"unsupported command kind: {resolved}")
    return resolved


def _normalize_snapshot_summary(raw_summary: Any) -> dict[str, Any]:
    if raw_summary is None:
        return {}
    if not isinstance(raw_summary, dict):
        raise ValueError("snapshot_summary must be a mapping when present")

    normalized: dict[str, Any] = {}
    field_order = (
        "snapshot_kind",
        "selector_name",
        "selector_value",
        "selector_valid",
        "result_kind",
        "result_field",
        "fault_reason",
    )
    for field_name in field_order:
        if field_name not in raw_summary:
            continue
        value = raw_summary[field_name]
        if field_name == "selector_value" and value is not None:
            normalized[field_name] = int(value)
        elif field_name == "selector_valid":
            normalized[field_name] = bool(value)
        else:
            normalized[field_name] = value
    return normalized


def _snapshot_signature(snapshot_summary: dict[str, Any]) -> str:
    if not snapshot_summary:
        return ""
    components = [
        str(snapshot_summary.get("snapshot_kind") or "unknown"),
        str(snapshot_summary.get("selector_name") or "none"),
        str(snapshot_summary.get("selector_value") if "selector_value" in snapshot_summary else "none"),
        str(snapshot_summary.get("result_kind") or "unknown"),
    ]
    if "fault_reason" in snapshot_summary:
        components.append(str(snapshot_summary.get("fault_reason") or "none"))
    return ":".join(components)


def _fault_snapshot_label(
    *,
    step_index: int,
    command_kind: str,
    snapshot_summary: dict[str, Any],
) -> str:
    if command_kind == "stat_snapshot":
        return f"{command_kind}:{_snapshot_signature(snapshot_summary) or 'fault'}:step_{step_index}"
    return f"fault_step_{step_index}"


def runtime_summary_from_program_request(request: ReferenceProgramRequest) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
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

    for step_index, step in enumerate(request.steps):
        command_kind = _resolved_command_kind(step)
        command_kind_sequence.append(command_kind)
        terminal_state = str(step.metadata.get("terminal_state") or "")
        if not terminal_state:
            terminal_state = "Faulted" if step.condition_values.get("fault_classified") else "Completed"
        snapshot_summary = _normalize_snapshot_summary(step.metadata.get("snapshot_summary"))
        snapshot_signature = _snapshot_signature(snapshot_summary)
        step_summary = {
            "step_name": step.step_name,
            "command_kind": command_kind,
            "terminal_state": terminal_state,
            "control_events": list(step.metadata.get("control_events", []) or []),
            "memory_domains": list(step.metadata.get("memory_domains", []) or []),
            "fabric_stages": list(step.metadata.get("fabric_stages", []) or []),
            "divergence_points": list(step.metadata.get("divergence_points", []) or []),
        }
        if snapshot_summary:
            step_summary["snapshot_summary"] = snapshot_summary
            step_summary["snapshot_signature"] = snapshot_signature
            snapshot_step_indices.append(step_index)
            snapshot_signature_sequence.append(snapshot_signature)
            snapshot_summary_sequence.append(snapshot_summary)
        if step.clear_fault_before_step:
            step_summary["clear_fault_before_step"] = True
            clear_fault_before_step_indices.append(step_index)
        if step.overwrite_visible_fault_snapshot:
            step_summary["overwrite_visible_fault_snapshot"] = True
            overwrite_fault_step_indices.append(step_index)
        if terminal_state == "Completed":
            completion_step_indices.append(step_index)
        if terminal_state == "Faulted":
            fault_step_indices.append(step_index)
            fault_snapshot_sequence.append(
                _fault_snapshot_label(
                    step_index=step_index,
                    command_kind=command_kind,
                    snapshot_summary=snapshot_summary,
                )
            )
        if terminal_state == "BarrierWaiting":
            barrier_wait_step_indices.append(step_index)
        steps.append(step_summary)

    terminal_state = str(steps[-1]["terminal_state"]) if steps else "Idle"
    return {
        "family": request.family,
        "reference_program_profile": str(request.metadata.get("reference_program_profile") or ""),
        "steps": steps,
        "step_count": len(steps),
        "terminal_state": terminal_state,
        "terminal_states": [str(step["terminal_state"]) for step in steps],
        "command_kind_sequence": command_kind_sequence,
        "completion_step_indices": completion_step_indices,
        "fault_step_indices": fault_step_indices,
        "barrier_wait_step_indices": barrier_wait_step_indices,
        "clear_fault_before_step_indices": clear_fault_before_step_indices,
        "overwrite_fault_step_indices": overwrite_fault_step_indices,
        "snapshot_step_indices": snapshot_step_indices,
        "snapshot_signature_sequence": snapshot_signature_sequence,
        "snapshot_summary_sequence": snapshot_summary_sequence,
        "fault_snapshot_sequence": fault_snapshot_sequence,
    }


@dataclass(frozen=True)
class ProgramProfileModel:
    control_event_names: tuple[str, ...]
    profile_templates: dict[str, dict[str, Any]]
    known_memory_domains: tuple[str, ...]
    known_fabric_stages: tuple[str, ...]
    allowed_divergence_points: tuple[str, ...]
    known_terminal_states: tuple[str, ...]

    @classmethod
    def from_authority(cls, authority: dict[str, Any]) -> "ProgramProfileModel":
        required_sections = (
            "program_control_event_taxonomy",
            "program_semantic_profiles",
            "memory_taxonomy",
            "fabric_taxonomy",
            "fused_step_state_machine",
        )
        missing_sections = [section for section in required_sections if section not in authority]
        if missing_sections:
            raise ValueError(
                "missing required program authority sections: " + ", ".join(missing_sections)
            )

        control_event_names = tuple(
            str(event.get("name") or "")
            for event in list(
                ((authority.get("program_control_event_taxonomy") or {}).get("events")) or []
            )
            if str(event.get("name") or "").strip()
        )
        if not control_event_names:
            raise ValueError("program_control_event_taxonomy.events must not be empty")

        known_memory_domains = tuple(
            str(domain.get("name") or "")
            for domain in list(((authority.get("memory_taxonomy") or {}).get("memory_domains")) or [])
            if str(domain.get("name") or "").strip()
        )
        known_fabric_stages = tuple(
            str(stage.get("name") or "")
            for stage in list(((authority.get("fabric_taxonomy") or {}).get("stages")) or [])
            if str(stage.get("name") or "").strip()
        )
        allowed_divergence_points = tuple(
            str(point)
            for point in list(((authority.get("fabric_taxonomy") or {}).get("allowed_divergence_points")) or [])
            if str(point).strip()
        )
        known_terminal_states = tuple(
            str(state.get("name") or "")
            for state in list(((authority.get("fused_step_state_machine") or {}).get("states")) or [])
            if str(state.get("name") or "").strip()
        )

        profiles = list(((authority.get("program_semantic_profiles") or {}).get("profiles")) or [])
        profile_templates: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            profile_name = str(profile.get("profile_name") or "").strip()
            if not profile_name:
                raise ValueError("program semantic profile missing profile_name")
            if profile_name in profile_templates:
                raise ValueError(f"duplicate program semantic profile: {profile_name}")
            step_templates = list(profile.get("step_templates") or [])
            if not step_templates:
                raise ValueError(f"program semantic profile {profile_name} has no step_templates")
            for step in step_templates:
                command_kind = str(step.get("command_kind") or "fused_step").strip()
                if command_kind not in _KNOWN_COMMAND_KINDS:
                    raise ValueError(
                        f"program semantic profile {profile_name} uses unknown command kind: "
                        f"{command_kind}"
                    )
                terminal_state = str(step.get("terminal_state") or "").strip()
                if terminal_state not in known_terminal_states:
                    raise ValueError(
                        f"program semantic profile {profile_name} uses unknown terminal state: "
                        f"{terminal_state}"
                    )
                if command_kind == "stat_snapshot" and terminal_state == "BarrierWaiting":
                    raise ValueError(
                        f"program semantic profile {profile_name} uses unsupported stat_snapshot "
                        "terminal state: BarrierWaiting"
                    )
                for event_name in list(step.get("control_events") or []):
                    if str(event_name) not in set(control_event_names):
                        raise ValueError(
                            f"program semantic profile {profile_name} uses unknown control event: "
                            f"{event_name}"
                        )
                for domain_name in list(step.get("memory_domains") or []):
                    if str(domain_name) not in set(known_memory_domains):
                        raise ValueError(
                            f"program semantic profile {profile_name} uses unknown memory domain: "
                            f"{domain_name}"
                        )
                for stage_name in list(step.get("fabric_stages") or []):
                    if str(stage_name) not in set(known_fabric_stages):
                        raise ValueError(
                            f"program semantic profile {profile_name} uses unknown fabric stage: "
                            f"{stage_name}"
                        )
                for point in list(step.get("divergence_points") or []):
                    if str(point) not in set(allowed_divergence_points):
                        raise ValueError(
                            f"program semantic profile {profile_name} uses unknown divergence point: "
                            f"{point}"
                        )
                if command_kind == "stat_snapshot":
                    snapshot_summary = _normalize_snapshot_summary(step.get("snapshot_summary"))
                    if not snapshot_summary:
                        raise ValueError(
                            f"program semantic profile {profile_name} stat_snapshot step "
                            "must declare snapshot_summary"
                        )
                    if not str(snapshot_summary.get("snapshot_kind") or "").strip():
                        raise ValueError(
                            f"program semantic profile {profile_name} stat_snapshot step "
                            "missing snapshot_kind"
                        )
                    if not str(snapshot_summary.get("result_kind") or "").strip():
                        raise ValueError(
                            f"program semantic profile {profile_name} stat_snapshot step "
                            "missing result_kind"
                        )
            profile_templates[profile_name] = dict(profile)

        return cls(
            control_event_names=control_event_names,
            profile_templates=profile_templates,
            known_memory_domains=known_memory_domains,
            known_fabric_stages=known_fabric_stages,
            allowed_divergence_points=allowed_divergence_points,
            known_terminal_states=known_terminal_states,
        )

    def build_request(
        self,
        *,
        family: str,
        profile_name: str,
        family_policy: dict[str, Any] | None = None,
    ) -> ReferenceProgramRequest:
        resolved_profile_name = str(profile_name or "").strip()
        if not resolved_profile_name:
            raise ValueError(f"reference_program_profile missing for family: {family}")
        if resolved_profile_name not in self.profile_templates:
            raise ValueError(
                f"reference_program_profile {resolved_profile_name} is not declared in authority"
            )

        resolved_family_policy = {} if family_policy is None else dict(family_policy)
        profile = self.profile_templates[resolved_profile_name]
        runtime_gate_divergence_points = _runtime_gate_divergence_points(
            resolved_family_policy,
            allowed_points=self.allowed_divergence_points,
        )
        steps: list[ReferenceProgramStep] = []
        for step_template in list(profile.get("step_templates") or []):
            terminal_state = str(step_template.get("terminal_state") or "").strip()
            command_kind = str(step_template.get("command_kind") or "fused_step").strip()
            divergence_points = list(step_template.get("divergence_points") or [])
            if bool(step_template.get("include_runtime_gate_divergence_points")):
                divergence_points.extend(runtime_gate_divergence_points)
            snapshot_summary = _normalize_snapshot_summary(step_template.get("snapshot_summary"))
            steps.append(
                ReferenceProgramStep(
                    step_name=str(step_template.get("step_name") or f"program_step_{len(steps)}"),
                    condition_values=_condition_values_for_terminal_state(terminal_state),
                    command_kind=command_kind,
                    metadata={
                        "command_kind": command_kind,
                        "terminal_state": terminal_state,
                        "control_events": list(step_template.get("control_events") or []),
                        "memory_domains": list(step_template.get("memory_domains") or []),
                        "fabric_stages": list(step_template.get("fabric_stages") or []),
                        "divergence_points": _dedupe_preserve(
                            [str(point) for point in divergence_points if str(point).strip()]
                        ),
                        "snapshot_summary": snapshot_summary,
                    },
                    clear_fault_before_step=bool(step_template.get("clear_fault_before_step")),
                    overwrite_visible_fault_snapshot=bool(
                        step_template.get("overwrite_visible_fault_snapshot")
                    ),
                )
            )

        return ReferenceProgramRequest(
            family=family,
            steps=steps,
            metadata={
                "reference_program_profile": resolved_profile_name,
                "semantic_statement": str(profile.get("semantic_statement") or ""),
            },
        )
