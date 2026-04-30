from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class FusedStepState:
    name: str
    entry_condition: str
    exit_condition: str
    architecturally_visible: bool
    microarchitectural_only: bool
    simulator_bookkeeping_only: bool
    counter_groups: List[str]


@dataclass
class CompletionBoundary:
    boundary_name: str
    required_conditions: List[str]


@dataclass
class StateMachine:
    semantic_statement: str
    completion_boundary: CompletionBoundary
    fault_boundary: CompletionBoundary
    visibility_domains: Dict[str, str]
    states: List[FusedStepState]


@dataclass
class MemoryDomain:
    name: str
    contains: List[str]
    architecturally_visible: bool
    shared_with: List[str]
    contention_scope: str
    persistence_scope: str
    notes: str


@dataclass
class MemoryTaxonomy:
    semantic_statement: str
    memory_domains: List[MemoryDomain]


@dataclass
class FabricStage:
    name: str
    description: str
    architecturally_visible: bool
    microarchitecturally_modeled: bool
    primary_counters: List[str]
    blocking_sources: List[str]


@dataclass
class FabricTaxonomy:
    semantic_statement: str
    stages: List[FabricStage]
    allowed_divergence_points: List[str]


@dataclass(frozen=True)
class ReferenceMemoryEvent:
    domain: str
    event: str
    contains: List[str]


@dataclass(frozen=True)
class ReferenceFabricEvent:
    stage: str
    event: str
    blocking_sources: List[str]


@dataclass(frozen=True)
class ReferenceDivergenceObservation:
    kind: str
    classification: str


@dataclass(frozen=True)
class ReferenceStepRequest:
    condition_values: Dict[str, bool]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceStepResult:
    terminal_state: str
    visited_states: List[str]
    completion_retired: bool
    faulted: bool
    architectural_state: Dict[str, Any]
    microarchitectural_progress: Dict[str, Any]
    simulator_bookkeeping: Dict[str, Any]
    memory_events: List[ReferenceMemoryEvent] = field(default_factory=list)
    fabric_events: List[ReferenceFabricEvent] = field(default_factory=list)
    divergence_observations: List[ReferenceDivergenceObservation] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceProgramStep:
    step_name: str
    condition_values: Dict[str, bool]
    command_kind: str = "fused_step"
    metadata: Dict[str, Any] = field(default_factory=dict)
    clear_fault_before_step: bool = False
    overwrite_visible_fault_snapshot: bool = False


@dataclass(frozen=True)
class ReferenceProgramRequest:
    family: str
    steps: List[ReferenceProgramStep]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceProgramTraceEntry:
    step_index: int
    step_name: str
    result: ReferenceStepResult
    command_kind: str = "fused_step"
    metadata: Dict[str, Any] = field(default_factory=dict)
    clear_fault_before_step: bool = False
    overwrite_visible_fault_snapshot: bool = False


@dataclass(frozen=True)
class ReferenceProgramResult:
    family: str
    step_count: int
    terminal_state: str
    terminal_states: List[str]
    entries: List[ReferenceProgramTraceEntry]
    command_kind_sequence: List[str] = field(default_factory=list)
    completion_step_indices: List[int] = field(default_factory=list)
    fault_step_indices: List[int] = field(default_factory=list)
    barrier_wait_step_indices: List[int] = field(default_factory=list)
    clear_fault_before_step_indices: List[int] = field(default_factory=list)
    overwrite_fault_step_indices: List[int] = field(default_factory=list)
    snapshot_step_indices: List[int] = field(default_factory=list)
    snapshot_signature_sequence: List[str] = field(default_factory=list)
    snapshot_summary_sequence: List[Dict[str, Any]] = field(default_factory=list)
    fault_snapshot_sequence: List[str] = field(default_factory=list)
    memory_domain_sequences: List[List[str]] = field(default_factory=list)
    fabric_stage_sequences: List[List[str]] = field(default_factory=list)
    divergence_point_sequences: List[List[str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
