// -*- c++ -*-
//
// LocalStorageTypes:
// - Shared enums/config structs for the on-chip local storage hierarchy.
// - Phase A focuses on object registration / observability, not runtime dataflow migration yet.

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace SST { namespace SnnDL {

enum class LocalStorageObjectKind {
    AddressableStore,
    QueueStore,
    RegisterFile
};

enum class LocalStorageScope {
    PerCore,
    PerPod,
    PerPe
};

struct LocalStorageObjectConfig {
    std::string name;
    LocalStorageObjectKind kind = LocalStorageObjectKind::AddressableStore;
    LocalStorageScope scope = LocalStorageScope::PerPe;
    bool enable = false;
    uint64_t capacity_bytes = 0;
    uint64_t line_bytes = 0;
    uint32_t banks = 1;
    uint32_t read_ports = 0;
    uint32_t write_ports = 0;
    uint32_t update_ports = 0;
    uint32_t queue_depth = 0;
    uint32_t entries = 0;
    uint32_t entry_bytes = 0;
};

struct LocalStorageStatsSnapshot {
    size_t objects_registered_total = 0;
    size_t objects_enabled_total = 0;
    uint64_t capacity_bytes_total = 0;
    uint64_t queue_slots_total = 0;
};

struct PhaseALocalStorageRegistrationConfig {
    size_t num_cores = 1;
    size_t num_pods = 1;

    LocalStorageObjectConfig activation_ingress{};
    LocalStorageObjectConfig weight_idx{};
    LocalStorageObjectConfig weight_value{};
    LocalStorageObjectConfig pod_metadata_template{};
    LocalStorageObjectConfig pod_owner_template{};
    LocalStorageObjectConfig pod_join_template{};
    LocalStorageObjectConfig pod_ready_template{};
    LocalStorageObjectConfig state_template{};
    LocalStorageObjectConfig activation_core_template{};
    LocalStorageObjectConfig acc_template{};
    LocalStorageObjectConfig rf_template{};
};

uint64_t localStorageEffectiveCapacityBytes(const LocalStorageObjectConfig& cfg);
bool localStorageObjectEnabled(const LocalStorageObjectConfig& cfg);

}} // namespace SST::SnnDL
