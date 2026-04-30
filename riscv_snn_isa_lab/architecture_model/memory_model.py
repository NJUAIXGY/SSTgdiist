from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from riscv_snn_isa_lab.architecture_model.model_types import MemoryDomain, MemoryTaxonomy, ReferenceMemoryEvent


@dataclass
class MemoryModel:
    taxonomy: MemoryTaxonomy

    @classmethod
    def from_authority(cls, authority: Dict[str, Any]) -> "MemoryModel":
        section = authority.get("memory_taxonomy", authority)
        if section is None:
            raise ValueError("authority missing memory_taxonomy")

        domains_config = section["memory_domains"]
        domains = [
            MemoryDomain(
                name=domain["name"],
                contains=list(domain.get("contains", [])),
                architecturally_visible=bool(domain["architecturally_visible"]),
                shared_with=list(domain.get("shared_with", [])),
                contention_scope=domain.get("contention_scope", ""),
                persistence_scope=domain.get("persistence_scope", ""),
                notes=domain.get("notes", ""),
            )
            for domain in domains_config
        ]

        taxonomy = MemoryTaxonomy(
            semantic_statement=section.get("semantic_statement", ""),
            memory_domains=domains,
        )

        return cls(taxonomy=taxonomy)

    def domain_names(self) -> list[str]:
        return [domain.name for domain in self.taxonomy.memory_domains]

    def domain_by_name(self, name: str) -> MemoryDomain:
        for domain in self.taxonomy.memory_domains:
            if domain.name == name:
                return domain
        raise ValueError(f"unknown memory domain: {name}")

    def account_domains(self, names: list[str]) -> list[ReferenceMemoryEvent]:
        events: list[ReferenceMemoryEvent] = []
        for name in names:
            domain = self.domain_by_name(name)
            events.append(
                ReferenceMemoryEvent(
                    domain=domain.name,
                    event=f"{domain.name}.access",
                    contains=list(domain.contains),
                )
            )
        return events
