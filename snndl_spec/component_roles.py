from __future__ import annotations

SUPPORTED_COMPONENT_ROLES: set[str] = {
    "router",
    "router.topology",
    "global_step_controller",
    "pe_mem_controller",
    "pe_mem_controller.backend",
    "pe_mem_bus",
    "weight_loader",
    "weight_loader.memory_if",
    "pe",
    "pe.nic",
    "pe.core",
    "pe.core.memory_if",
    "pe.l1_cache",
}

