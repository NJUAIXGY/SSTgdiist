from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from riscv_snn_isa_lab.architecture_model.model_types import (
    FabricStage,
    FabricTaxonomy,
    ReferenceDivergenceObservation,
    ReferenceFabricEvent,
)


@dataclass
class FabricModel:
    taxonomy: FabricTaxonomy

    @classmethod
    def from_authority(cls, authority: Dict[str, Any]) -> "FabricModel":
        section = authority.get("fabric_taxonomy", authority)
        if section is None:
            raise ValueError("authority missing fabric_taxonomy")

        stages_config = section["stages"]
        stages = [
            FabricStage(
                name=stage["name"],
                description=stage.get("description", ""),
                architecturally_visible=bool(stage["architecturally_visible"]),
                microarchitecturally_modeled=bool(stage.get("microarchitecturally_modeled", True)),
                primary_counters=list(stage.get("primary_counters", [])),
                blocking_sources=list(stage.get("blocking_sources", [])),
            )
            for stage in stages_config
        ]

        taxonomy = FabricTaxonomy(
            semantic_statement=section.get("semantic_statement", ""),
            stages=stages,
            allowed_divergence_points=list(section.get("allowed_divergence_points", [])),
        )

        return cls(taxonomy=taxonomy)

    def stage_names(self) -> list[str]:
        return [stage.name for stage in self.taxonomy.stages]

    @property
    def allowed_divergence_points(self) -> tuple[str, ...]:
        return tuple(self.taxonomy.allowed_divergence_points)

    def stage_by_name(self, name: str) -> FabricStage:
        for stage in self.taxonomy.stages:
            if stage.name == name:
                return stage
        raise ValueError(f"unknown fabric stage: {name}")

    def account_stages(self, names: list[str]) -> list[ReferenceFabricEvent]:
        events: list[ReferenceFabricEvent] = []
        for name in names:
            stage = self.stage_by_name(name)
            events.append(
                ReferenceFabricEvent(
                    stage=stage.name,
                    event=f"{stage.name}.transit",
                    blocking_sources=list(stage.blocking_sources),
                )
            )
        return events

    def account_divergence_points(self, names: list[str]) -> list[ReferenceDivergenceObservation]:
        allowed = set(self.taxonomy.allowed_divergence_points)
        observations: list[ReferenceDivergenceObservation] = []
        for name in names:
            if name not in allowed:
                raise ValueError(f"unknown divergence point: {name}")
            observations.append(
                ReferenceDivergenceObservation(
                    kind=name,
                    classification="allowed_divergence",
                )
            )
        return observations
